"""eSCL (AirScan) scanner backend — works with any AirPrint printer on macOS/Linux.

eSCL is an HTTP protocol built into every modern wireless printer.
macOS uses it under the hood in Image Capture. No extra drivers needed.

Discovery: reads the device URI from CUPS (`lpstat -v`) and probes each printer
for the eSCL ScannerCapabilities endpoint to confirm scanner support.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import time
from urllib.parse import unquote, urlparse

import httpx
from loguru import logger

from app.scanner.driver import ScannerDevice, ScanOptions


_ESCL_PATHS = ["/eSCL", "/eSCL/", "/escl"]          # common mount points
# Epson printers serve eSCL on HTTP:443 (unusual but real); always probe 443 in addition
# to whatever port was resolved.
_EXTRA_PORTS = [443, 80]

# eSCL scan request XML. Notes:
#   - xmlns:escl required so ContentRegionUnits value "escl:ThreeHundredthsOfInches" resolves.
#   - DocumentFormat must be image/jpeg — eSCL printers rarely expose PNG.
#   - Width/Height are in 1/300ths of an inch regardless of actual DPI (eSCL spec §4.3).
_SCAN_XML_TEMPLATE = """\
<?xml version="1.0" encoding="UTF-8"?>
<scan:ScanSettings
    xmlns:scan="http://schemas.hp.com/imaging/escl/2011/05/03"
    xmlns:escl="http://schemas.hp.com/imaging/escl/2011/05/03"
    xmlns:pwg="http://www.pwg.org/schemas/2010/12/sm">
  <pwg:Version>2.63</pwg:Version>
  <scan:Intent>TextAndGraphic</scan:Intent>
  <pwg:ScanRegions>
    <pwg:ScanRegion>
      <pwg:ContentRegionUnits>escl:ThreeHundredthsOfInches</pwg:ContentRegionUnits>
      <pwg:Width>{width_300}</pwg:Width>
      <pwg:Height>{height_300}</pwg:Height>
      <pwg:XOffset>0</pwg:XOffset>
      <pwg:YOffset>0</pwg:YOffset>
    </pwg:ScanRegion>
  </pwg:ScanRegions>
  <scan:ColorMode>{color_mode}</scan:ColorMode>
  <scan:XResolution>{dpi}</scan:XResolution>
  <scan:YResolution>{dpi}</scan:YResolution>
  <pwg:InputSource>{source}</pwg:InputSource>
  <pwg:DocumentFormat>image/jpeg</pwg:DocumentFormat>
</scan:ScanSettings>"""


class ESCLBackend:
    """Discover and scan via eSCL on printers already registered with CUPS."""

    def list_devices(self) -> list[ScannerDevice]:
        """Return all CUPS printers that answer the eSCL ScannerCapabilities probe."""
        printer_uris = self._cups_printer_uris()
        devices: list[ScannerDevice] = []

        for name, uri in printer_uris.items():
            base = self._escl_base(uri)
            if base:
                logger.debug(f"eSCL found: {name} @ {base}")
                devices.append(ScannerDevice(
                    id=base,
                    name=name,
                    source="escl",
                ))

        return devices

    def scan(self, device_id: str, options: ScanOptions) -> bytes:
        """Trigger an eSCL scan and return JPEG image bytes.

        *device_id* is the eSCL base URL (e.g. http://192.168.1.10/eSCL).
        """
        color_map = {"gray": "Grayscale8", "color": "RGB24", "lineart": "BlackAndWhite1"}
        source_map = {"Flatbed": "Platen", "ADF": "Feeder", "ADF Front": "Feeder"}

        # A4 in 1/300-inch units (eSCL always uses 1/300 for region dimensions)
        xml = _SCAN_XML_TEMPLATE.format(
            dpi=options.dpi,
            color_mode=color_map.get(options.color_mode, "Grayscale8"),
            source=source_map.get(options.source, "Platen"),
            width_300=int(8.27 * 300),
            height_300=int(11.69 * 300),
        )

        with httpx.Client(timeout=120.0, verify=False) as client:
            # 0. Ensure scanner is ready — cancel any stuck job first, then wait for Idle.
            state = self._scanner_state(client, device_id)
            if state != "Idle":
                logger.info(f"eSCL scanner is {state!r} — attempting to cancel lingering job")
                self._cancel_stuck_jobs(client, device_id)
                self._wait_for_idle(client, device_id, max_wait_s=90)

            # 1. Create scan job — retry once if the first attempt gets 503
            job_uri: str | None = None
            for attempt in range(2):
                resp = client.post(
                    f"{device_id}/ScanJobs",
                    content=xml.encode(),
                    headers={"Content-Type": "text/xml"},
                )
                if resp.status_code in (200, 201):
                    job_uri = resp.headers.get("Location")
                    break
                if resp.status_code == 503 and attempt == 0:
                    # One more forced cancel + wait before giving up
                    logger.warning("eSCL 503 on first attempt — forcing cancel and retry")
                    self._cancel_stuck_jobs(client, device_id)
                    self._wait_for_idle(client, device_id, max_wait_s=60)
                    continue
                # Non-503 error or second failure — give up
                state = self._scanner_state(client, device_id)
                raise RuntimeError(
                    f"Scanner not ready (state={state!r}). "
                    "Make sure the scanner lid is closed and no other app is using it, "
                    "then try again."
                )

            if not job_uri:
                raise RuntimeError("eSCL: no Location header in ScanJob response")

            # Make absolute if the printer returned a relative path
            if job_uri.startswith("/"):
                parsed = urlparse(device_id)
                job_uri = f"{parsed.scheme}://{parsed.netloc}{job_uri}"

            logger.info(f"eSCL scan job created: {job_uri}")

            # 2. Poll for the scanned document (up to 120 s)
            doc_url = f"{job_uri}/NextDocument"
            for attempt in range(60):
                time.sleep(2)
                img_resp = client.get(doc_url)
                if img_resp.status_code == 200:
                    logger.info(f"eSCL scan complete: {len(img_resp.content)} bytes")
                    # Best-effort delete of the completed job so the scanner returns to Idle
                    try:
                        client.delete(job_uri, timeout=5.0)
                    except Exception:
                        pass
                    return img_resp.content
                if img_resp.status_code == 404:
                    raise RuntimeError(
                        "eSCL: document not available — make sure the item is placed on the flatbed"
                    )
                logger.debug(f"eSCL waiting for scan (attempt {attempt+1}/60): {img_resp.status_code}")

            raise RuntimeError("eSCL scan timed out after 120 s")

    @staticmethod
    def _scanner_state(client: httpx.Client, device_id: str) -> str:
        """Return the current scanner state string, e.g. 'Idle' or 'Processing'."""
        try:
            r = client.get(f"{device_id}/ScannerStatus", timeout=5.0)
            m = re.search(r"<pwg:State>(.+?)</pwg:State>", r.text)
            return m.group(1) if m else "Unknown"
        except Exception:
            return "Unknown"

    @staticmethod
    def _cancel_stuck_jobs(client: httpx.Client, device_id: str) -> None:
        """Best-effort cancellation of any lingering eSCL scan jobs.

        Strategy:
        1. Try GET /ScanJobs to get a job list (not all scanners support this).
        2. Fall back to DELETE on job IDs 1–5 (covers typical Epson sequential IDs).
        """
        jobs_url = f"{device_id}/ScanJobs"

        # Try to list jobs first
        try:
            r = client.get(jobs_url, timeout=5.0)
            if r.status_code == 200:
                job_uris = re.findall(r"<pwg:JobUri>(.+?)</pwg:JobUri>", r.text)
                if not job_uris:
                    # Some scanners return the job URIs as href attributes
                    job_uris = re.findall(r'href="([^"]+ScanJobs[^"]*)"', r.text)
                for uri in job_uris:
                    if uri.startswith("/"):
                        parsed = urlparse(device_id)
                        uri = f"{parsed.scheme}://{parsed.netloc}{uri}"
                    try:
                        client.delete(uri, timeout=5.0)
                        logger.info(f"eSCL cancelled job: {uri}")
                    except Exception:
                        pass
                if job_uris:
                    return
        except Exception:
            pass

        # Fallback: try DELETE on sequential job IDs (Epson typically uses /ScanJobs/N)
        for job_id in range(1, 6):
            try:
                r = client.delete(f"{jobs_url}/{job_id}", timeout=3.0)
                if r.status_code in (200, 204):
                    logger.info(f"eSCL cancelled job ID {job_id}")
            except Exception:
                pass

    def _wait_for_idle(self, client: httpx.Client, device_id: str, max_wait_s: int = 90) -> None:
        """Poll ScannerStatus until state is Idle or timeout."""
        deadline = time.monotonic() + max_wait_s
        while time.monotonic() < deadline:
            state = self._scanner_state(client, device_id)
            if state == "Idle":
                return
            logger.debug(f"eSCL scanner state={state!r}, waiting for Idle…")
            time.sleep(3)
        state = self._scanner_state(client, device_id)
        if state != "Idle":
            logger.warning(f"Scanner did not reach Idle in {max_wait_s}s (state={state!r}), proceeding anyway")

    # ── Private ───────────────────────────────────────────────────────────────

    @staticmethod
    def _cups_printer_uris() -> dict[str, str]:
        """Return {printer_name: device_uri} from `lpstat -v`."""
        if not shutil.which("lpstat"):
            return {}
        try:
            result = subprocess.run(
                ["lpstat", "-v"], capture_output=True, text=True, timeout=5
            )
            uris: dict[str, str] = {}
            for line in result.stdout.splitlines():
                # Format: device for PrinterName: ipp://hostname/ipp/print
                m = re.match(r"device for ([^:]+):\s+(\S+)", line)
                if m:
                    uris[m.group(1).strip()] = m.group(2).strip()
            return uris
        except Exception as exc:
            logger.debug(f"lpstat failed: {exc}")
            return {}

    @staticmethod
    def _escl_base(device_uri: str) -> str | None:
        """Probe the printer URI for an eSCL ScannerCapabilities endpoint.

        Handles ipp://, ipps://, http://, https://, and dnssd:// (Bonjour) URIs.
        Returns the eSCL base URL if found, else None.
        """
        parsed = urlparse(device_uri)

        if parsed.scheme == "dnssd":
            host, resolved_port, scheme = ESCLBackend._resolve_dnssd(device_uri)
            if not host:
                return None
            candidate_ports = list(dict.fromkeys([resolved_port] + _EXTRA_PORTS))
        elif parsed.scheme in ("ipp", "ipps", "http", "https"):
            scheme = "https" if parsed.scheme in ("ipps", "https") else "http"
            host = parsed.hostname
            resolved_port = parsed.port or (443 if scheme == "https" else 80)
            candidate_ports = list(dict.fromkeys([resolved_port] + _EXTRA_PORTS))
        else:
            return None

        # Probe all candidate ports × paths until we find ScannerCapabilities.
        # Use plain HTTP on all ports — Epson (and some others) serve eSCL on
        # HTTP:443 rather than HTTPS:443.
        for port in candidate_ports:
            for scheme_try in ["http", "https"]:
                base = f"{scheme_try}://{host}:{port}"
                for path in _ESCL_PATHS:
                    url = f"{base}{path}/ScannerCapabilities"
                    try:
                        r = httpx.get(url, timeout=2.0, verify=False)
                        if r.status_code == 200 and (
                            "ScannerCapabilities" in r.text or "escl" in r.text.lower()
                        ):
                            return f"{base}{path}"
                    except Exception:
                        continue

        return None

    @staticmethod
    def _resolve_dnssd(dnssd_uri: str) -> tuple[str | None, int, str]:
        """Resolve a dnssd:// URI → (hostname, port, scheme) via dns-sd lookup.

        Example URI: dnssd://EPSON%20L4160%20Series._ipps._tcp.local./?uuid=...
        """
        netloc = unquote(urlparse(dnssd_uri).netloc)  # "EPSON L4160 Series._ipps._tcp.local."

        # Isolate the service name by finding the _type._proto part
        m = re.search(r'\.(_.+?\._(tcp|udp))', netloc)
        if not m:
            return None, 80, "http"

        service_name = netloc[: m.start()]              # "EPSON L4160 Series"
        rest = netloc[m.start() + 1 :]                  # "_ipps._tcp.local."
        parts = rest.split(".")
        service_type = ".".join(parts[:2])               # "_ipps._tcp"
        domain = ".".join(parts[2:]).rstrip(".")         # "local"
        scheme = "https" if "_ipps" in service_type else "http"

        try:
            # dns-sd -L runs indefinitely; kill it after getting the first result.
            proc = subprocess.Popen(
                ["dns-sd", "-L", service_name, service_type, domain],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            )
            try:
                stdout, _ = proc.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                stdout, _ = proc.communicate()

            hit = re.search(r"can be reached at (\S+):(\d+)", stdout)
            if hit:
                host = hit.group(1).rstrip(".")
                port = int(hit.group(2))
                logger.debug(f"dnssd resolved: {service_name} → {host}:{port}")
                return host, port, scheme
        except Exception as exc:
            logger.debug(f"dns-sd lookup failed for {service_name!r}: {exc}")

        return None, 80, "http"


def is_available() -> bool:
    return shutil.which("lpstat") is not None
