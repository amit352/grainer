"""Main image-processing pipeline — orchestrates all vision steps."""
from __future__ import annotations

import time
from pathlib import Path

import cv2
import numpy as np
from loguru import logger

from app.core.config import settings
from app.models.domain import GrainMeasurement, ProcessingParams, ScanResult
from app.services.stats_service import compute_statistics
from app.vision.measurement import GrainMeasurer
from app.vision.segmentation import WatershedSegmenter
from app.vision.visualization import GrainVisualizer


class ImageProcessor:
    """End-to-end grain measurement pipeline.

    Usage::
        processor = ImageProcessor()
        result = processor.process(image_bytes, filename="scan.png", params=params)
    """

    def __init__(self) -> None:
        self._visualizer = GrainVisualizer()

    # ── Public ───────────────────────────────────────────────────────────────

    def process(
        self,
        image_bytes: bytes,
        filename: str,
        params: ProcessingParams | None = None,
        save_annotated: bool = True,
        auto_params: bool = False,
    ) -> ScanResult:
        """Full pipeline: raw bytes → ScanResult with measurements + annotated image.

        If *auto_params* is True (or *params* is None), the pipeline analyses the
        image first and picks invert_threshold, morph kernel, watershed distance,
        and area bounds automatically.
        """
        if auto_params or params is None:
            from app.vision.auto_params import auto_detect_params
            base_dpi = params.dpi if params is not None else 300
            params = auto_detect_params(image_bytes, dpi=base_dpi)
            logger.info(f"Auto-detected params: {params.model_dump()}")

        t0 = time.perf_counter()
        logger.info(f"Processing '{filename}' at {params.dpi} DPI")

        bgr = self._load(image_bytes)
        h, w = bgr.shape[:2]

        # ── Reference-card auto-calibration ──────────────────────────────────
        effective_dpi = params.dpi
        card_mask_pts: np.ndarray | None = None
        if params.reference_card:
            from app.calibration.calibrator import detect_card_px_per_mm
            detected_px_per_mm, card_mask_pts = detect_card_px_per_mm(bgr)
            if detected_px_per_mm:
                effective_dpi = int(round(detected_px_per_mm * 25.4))
                logger.info(
                    f"Card calibration: {detected_px_per_mm:.3f} px/mm "
                    f"→ effective DPI {effective_dpi}"
                )
            else:
                logger.warning("Reference card requested but not detected; using DPI setting")

        gray = self._to_grayscale(bgr)
        if params.use_multichannel:
            binary = self._fuse_channels(bgr, gray, params)
        else:
            blurred = self._blur(gray, params.gaussian_blur_kernel)
            binary = self._threshold(
                blurred, params.adaptive_block_size, params.adaptive_c,
                params.invert_threshold, params.use_global_threshold,
            )
        cleaned = self._morphology(binary, params.morph_kernel_size, params.morph_iterations)
        cleaned = self._fill_holes(cleaned)

        # Erase the card region so it isn't segmented as a grain
        if card_mask_pts is not None:
            cv2.fillPoly(cleaned, [card_mask_pts], 0)

        # Erase remaining artifacts before watershed — anything below half the
        # minimum accepted grain area cannot be a valid grain and would otherwise
        # become a spurious watershed seed.
        cleaned = self._remove_small_components(cleaned, max(30, params.min_grain_area_px // 2))

        segmenter = WatershedSegmenter(min_distance=params.watershed_min_distance)
        labels = segmenter.segment(cleaned)

        measurer = GrainMeasurer(
            dpi=effective_dpi,
            min_area_px=params.min_grain_area_px,
            max_area_px=params.max_grain_area_px,
        )
        measurements = measurer.measure_all(labels, intensity_image=gray)

        measurements, cluster_est, cluster_regions = self._split_anomaly_clusters(
            measurements, labels, cleaned,
            dpi=effective_dpi,
            min_area_px=params.min_grain_area_px,
            max_area_px=params.max_grain_area_px,
        )

        stats = compute_statistics(measurements)

        annotated_path: str | None = None
        if save_annotated and (measurements or cluster_regions):
            annotated = self._visualizer.annotate(bgr, measurements, labels, cluster_regions)
            # Draw card outline on annotated image so user can verify detection
            if card_mask_pts is not None:
                cv2.polylines(annotated, [card_mask_pts], True, (255, 140, 0), 3)
                cv2.putText(annotated, "REF CARD", tuple(card_mask_pts[0]),
                            cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 140, 0), 2)
            annotated_path = self._save_annotated(annotated, filename)

        elapsed = time.perf_counter() - t0
        logger.info(f"Done: {len(measurements)} grains in {elapsed:.2f}s")

        detected = len(measurements)
        px_per_mm = effective_dpi / 25.4
        return ScanResult(
            filename=filename,
            dpi=effective_dpi,
            image_width_px=w,
            image_height_px=h,
            image_width_mm=w / px_per_mm,
            image_height_mm=h / px_per_mm,
            detected_count=detected,
            cluster_estimated_count=cluster_est,
            grain_count=detected + cluster_est,
            processing_time_s=elapsed,
            measurements=measurements,
            statistics=stats,
            annotated_image_path=annotated_path,
            params=params,
            cluster_regions=cluster_regions,
        )

    # ── Individual pipeline steps (also useful for testing) ──────────────────

    @staticmethod
    def load_image(image_bytes: bytes) -> np.ndarray:
        """Decode image bytes → BGR ndarray. Raises ValueError on failure."""
        return ImageProcessor._load(image_bytes)

    @staticmethod
    def preprocess(
        image_bytes: bytes,
        params: ProcessingParams | None = None,
    ) -> tuple[np.ndarray, np.ndarray]:
        """Return (bgr_original, cleaned_binary) without running segmentation."""
        if params is None:
            params = ProcessingParams()
        bgr = ImageProcessor._load(image_bytes)
        gray = ImageProcessor._to_grayscale(bgr)
        blurred = ImageProcessor._blur(gray, params.gaussian_blur_kernel)
        binary = ImageProcessor._threshold(
            blurred, params.adaptive_block_size, params.adaptive_c,
            params.invert_threshold, params.use_global_threshold,
        )
        cleaned = ImageProcessor._morphology(binary, params.morph_kernel_size, params.morph_iterations)
        return bgr, cleaned

    # ── Private helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _fuse_channels(
        bgr: np.ndarray,
        gray: np.ndarray,
        params: "ProcessingParams",  # noqa: F821
    ) -> np.ndarray:
        """OR-fuse three binary masks for better grain recall.

        Channel 1 — Grayscale (standard): catches typical grains on light background.
        Channel 2 — CLAHE: recovers grains in unevenly lit regions (scan edges/shadows).
        Channel 3 — HSV Saturation (color images only): catches chalky or discoloured
                    grains whose saturation differs from the background.
        """
        # ── Channel 1: standard grayscale ────────────────────────────────────
        blurred = ImageProcessor._blur(gray, params.gaussian_blur_kernel)
        mask_gray = ImageProcessor._threshold(
            blurred, params.adaptive_block_size, params.adaptive_c,
            params.invert_threshold, params.use_global_threshold,
        )

        # ── Channel 2: CLAHE ─────────────────────────────────────────────────
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        gray_clahe = clahe.apply(gray)
        blurred_clahe = ImageProcessor._blur(gray_clahe, params.gaussian_blur_kernel)
        mask_clahe = ImageProcessor._threshold(
            blurred_clahe, params.adaptive_block_size, params.adaptive_c,
            params.invert_threshold, params.use_global_threshold,
        )

        # ── Channel 3: HSV saturation (skip on grayscale images) ─────────────
        hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
        sat = hsv[:, :, 1]
        if sat.mean() > 8:          # colour image — saturation channel is informative
            blurred_sat = ImageProcessor._blur(sat, params.gaussian_blur_kernel)
            # Grains typically have higher saturation than a white/grey background
            mask_sat = ImageProcessor._threshold(
                blurred_sat, params.adaptive_block_size, c=5,
                invert=False, use_global=False,
            )
            fused = cv2.bitwise_or(mask_gray, cv2.bitwise_or(mask_clahe, mask_sat))
        else:
            fused = cv2.bitwise_or(mask_gray, mask_clahe)

        logger.debug(
            f"Multi-channel fusion: gray={mask_gray.sum()//255} "
            f"clahe={mask_clahe.sum()//255} → fused={fused.sum()//255} foreground px"
        )
        return fused

    @staticmethod
    def _split_anomaly_clusters(
        measurements: list,
        labels: np.ndarray,
        cleaned: np.ndarray,
        dpi: int,
        min_area_px: int,
        max_area_px: int,
    ) -> tuple[list, int, list]:
        """Re-segment touching/merged/oversized grains into individual grains.

        For each grain flagged as "touching", "merged", or "oversized":
          1. Extract its binary sub-region from *cleaned*.
          2. Run a tighter watershed (smaller min_distance) to split the cluster.
          3. If ≥2 sub-grains are found: replace the merged measurement with
             individual GrainMeasurement objects (recovered_from_cluster=True).
          4. If the cluster cannot be split: record a ClusterRegion (excluded
             from quality; drawn as a red overlay with estimated count).

        Returns (updated_measurements, cluster_estimated_count, cluster_regions).
        """
        from scipy.ndimage import distance_transform_edt, gaussian_filter as gf
        from skimage.feature import peak_local_max
        from skimage.segmentation import watershed as skimage_ws
        from skimage.measure import regionprops

        from app.models.domain import BoundingBox, ClusterRegion, GrainMeasurement

        _MM_PER_INCH = 25.4
        px_per_mm = dpi / _MM_PER_INCH
        px2 = px_per_mm ** 2

        # All anomaly types are treated as potential clusters to resolve.
        def _is_cluster(m) -> bool:
            return bool(m.anomaly_flags)

        clean_grains   = [m for m in measurements if not _is_cluster(m)]
        cluster_grains = [m for m in measurements if _is_cluster(m)]

        if not cluster_grains:
            return measurements, 0

        # Estimate typical single-grain area from non-cluster grains
        if len(clean_grains) >= 5:
            clean_areas = np.array([m.area_px for m in clean_grains])
            median_area = float(np.median(clean_areas))
        elif measurements:
            all_areas = np.array([m.area_px for m in measurements])
            median_area = float(np.percentile(all_areas, 35))
        else:
            median_area = 500.0

        typical_radius = float(np.sqrt(median_area / np.pi))
        # Tighter min_distance for the re-split (vs 0.70 used in global pass)
        tight_min_dist = max(4, int(typical_radius * 0.35))
        marker_r       = max(2, int(typical_radius * 0.12))

        recovered: list = []
        cluster_regions: list = []
        cluster_estimated_count = 0
        next_idx = max((m.grain_index for m in measurements), default=-1) + 1
        img_h, img_w = labels.shape

        for m in cluster_grains:
            # Locate the watershed label for this grain at its centroid
            cy = int(round(m.centroid_y_px))
            cx = int(round(m.centroid_x_px))
            cy = max(0, min(cy, img_h - 1))
            cx = max(0, min(cx, img_w - 1))

            label_id = int(labels[cy, cx])
            if label_id == 0:
                # Centroid fell on background — scan neighbourhood
                for dy in range(-5, 6):
                    for dx in range(-5, 6):
                        ny, nx = cy + dy, cx + dx
                        if 0 <= ny < img_h and 0 <= nx < img_w and labels[ny, nx]:
                            label_id = int(labels[ny, nx])
                            break
                    if label_id:
                        break
            if label_id == 0:
                n_est = max(2, round(m.area_px / median_area))
                cluster_estimated_count += n_est
                cluster_regions.append(ClusterRegion(
                    bbox=m.bbox, estimated_count=n_est,
                    centroid_x_px=m.centroid_x_px, centroid_y_px=m.centroid_y_px,
                ))
                continue

            # Sub-region bounding box with padding
            pad = 12
            y1 = max(0, m.bbox.y - pad)
            y2 = min(img_h, m.bbox.y + m.bbox.height + pad)
            x1 = max(0, m.bbox.x - pad)
            x2 = min(img_w, m.bbox.x + m.bbox.width + pad)

            # Binary mask of exactly this watershed label
            sub_mask = (labels[y1:y2, x1:x2] == label_id).astype(np.uint8)
            if sub_mask.sum() < min_area_px:
                continue

            n_expected = max(2, round(m.area_px / median_area))

            # Distance transform with stronger smoothing to suppress texture noise
            dist    = distance_transform_edt(sub_mask).astype(np.float32)
            sigma   = max(2.0, typical_radius * 0.20)
            d_smooth = gf(dist, sigma=sigma)
            d_norm   = d_smooth / (d_smooth.max() + 1e-8)

            coords = peak_local_max(
                d_norm,
                min_distance=tight_min_dist,
                labels=sub_mask.astype(bool),
                exclude_border=False,
                num_peaks=n_expected,
            )

            if len(coords) < 2:
                cluster_estimated_count += n_expected
                cluster_regions.append(ClusterRegion(
                    bbox=m.bbox, estimated_count=n_expected,
                    centroid_x_px=m.centroid_x_px, centroid_y_px=m.centroid_y_px,
                ))
                logger.info(
                    f"Cluster grain #{m.grain_index}: area={m.area_px:.0f} "
                    f"n_exp={n_expected} → unsplittable"
                )
                continue

            # Place disc markers and watershed
            markers = np.zeros(sub_mask.shape, dtype=np.int32)
            for i, (r, c) in enumerate(coords, start=1):
                cv2.circle(markers, (int(c), int(r)), marker_r, i, -1)

            sub_labels = skimage_ws(-d_smooth, markers, mask=sub_mask.astype(bool))
            n_found    = int(sub_labels.max())

            if n_found < 2:
                cluster_estimated_count += n_expected
                cluster_regions.append(ClusterRegion(
                    bbox=m.bbox, estimated_count=n_expected,
                    centroid_x_px=m.centroid_x_px, centroid_y_px=m.centroid_y_px,
                ))
                continue

            # Measure each sub-grain and emit individual GrainMeasurement objects
            props = regionprops(sub_labels)
            split_ok = []

            for prop in props:
                area_px = float(prop.area)
                if not (min_area_px * 0.3 <= area_px <= max_area_px):
                    continue

                major_px = float(prop.major_axis_length)
                minor_px = max(float(prop.minor_axis_length), 1e-6)
                cy_s, cx_s = prop.centroid
                cy_full    = cy_s + y1
                cx_full    = cx_s + x1
                mr, mc, mR, mC = prop.bbox

                split_ok.append(GrainMeasurement(
                    grain_index=next_idx,
                    area_px=area_px,
                    perimeter_px=float(prop.perimeter),
                    major_axis_px=major_px,
                    minor_axis_px=minor_px,
                    centroid_x_px=float(cx_full),
                    centroid_y_px=float(cy_full),
                    area_mm2=area_px / px2,
                    perimeter_mm=float(prop.perimeter) / px_per_mm,
                    major_axis_mm=major_px / px_per_mm,
                    minor_axis_mm=minor_px / px_per_mm,
                    centroid_x_mm=float(cx_full) / px_per_mm,
                    centroid_y_mm=float(cy_full) / px_per_mm,
                    aspect_ratio=float(max(major_px / minor_px, 1.0)),
                    orientation_deg=float(np.degrees(prop.orientation)),
                    solidity=float(prop.solidity) if hasattr(prop, "solidity") else None,
                    eccentricity=float(prop.eccentricity) if hasattr(prop, "eccentricity") else None,
                    bbox=BoundingBox(
                        x=int(mc + x1), y=int(mr + y1),
                        width=int(mC - mc), height=int(mR - mr),
                    ),
                    anomaly_flags=[],
                    recovered_from_cluster=True,
                ))
                next_idx += 1

            if len(split_ok) >= 2:
                recovered.extend(split_ok)
                logger.info(
                    f"Cluster grain #{m.grain_index}: area={m.area_px:.0f} "
                    f"n_exp={n_expected} → split into {len(split_ok)} grains"
                )
            else:
                cluster_estimated_count += n_expected
                cluster_regions.append(ClusterRegion(
                    bbox=m.bbox, estimated_count=n_expected,
                    centroid_x_px=m.centroid_x_px, centroid_y_px=m.centroid_y_px,
                ))
                logger.info(
                    f"Cluster grain #{m.grain_index}: split yielded {len(split_ok)} "
                    f"valid sub-grains → estimated {n_expected}"
                )

        final = clean_grains + recovered
        for i, m_item in enumerate(final):
            setattr(m_item, "grain_index", i)

        logger.info(
            f"Cluster split: {len(cluster_grains)} anomalies → "
            f"{len(recovered)} recovered, {cluster_estimated_count} estimated, "
            f"{len(cluster_regions)} red regions"
        )
        return final, cluster_estimated_count, cluster_regions

    @staticmethod
    def _resegment_anomalies(
        labels: np.ndarray,
        cleaned: np.ndarray,
        flagged: list,
        original_min_dist: int,
    ) -> np.ndarray:
        """Re-run watershed on each flagged region with half the min_distance.

        For each touching/merged grain:
          1. Extract its binary sub-region from *cleaned*.
          2. Re-watershed with min_distance // 2.
          3. If it yields ≥2 sub-regions, assign new unique label IDs.
          4. Leave unchanged if it still can't be split (keep original label).
        """
        from scipy.ndimage import distance_transform_edt, gaussian_filter
        from skimage.feature import peak_local_max
        from skimage.segmentation import watershed as skimage_watershed

        new_labels  = labels.copy()
        next_id     = int(labels.max()) + 1
        tight_dist  = max(5, original_min_dist // 2)
        n_split     = 0

        for m in flagged:
            # Find the watershed label at this grain's centroid
            cy = int(round(m.centroid_y_px))
            cx = int(round(m.centroid_x_px))
            if cy >= labels.shape[0] or cx >= labels.shape[1]:
                continue
            label_id = int(labels[cy, cx])
            if label_id == 0:
                continue

            # Padded bounding box in image coordinates
            pad = 8
            y1 = max(0, m.bbox.y - pad)
            y2 = min(labels.shape[0], m.bbox.y + m.bbox.height + pad)
            x1 = max(0, m.bbox.x - pad)
            x2 = min(labels.shape[1], m.bbox.x + m.bbox.width + pad)

            # Binary mask of just this grain inside the sub-window
            sub_mask = (labels[y1:y2, x1:x2] == label_id).astype(np.uint8)
            if sub_mask.sum() == 0:
                continue

            # Distance transform + smoothing (matches WatershedSegmenter)
            dist = distance_transform_edt(sub_mask).astype(np.float32)
            sigma = max(tight_dist / 4.0, 1.0)
            dist_smooth = gaussian_filter(dist, sigma=sigma)
            dist_norm = dist_smooth / (dist_smooth.max() + 1e-8)

            coords = peak_local_max(
                dist_norm,
                min_distance=tight_dist,
                labels=sub_mask.astype(bool),
                exclude_border=False,
            )
            if len(coords) < 2:
                continue  # still can't split — leave as-is

            # Build markers and watershed the sub-region
            markers = np.zeros(sub_mask.shape, dtype=np.int32)
            for i, (r, c) in enumerate(coords, start=1):
                markers[r, c] = i
            sub_new = skimage_watershed(-dist_norm, markers, mask=sub_mask.astype(bool))

            n_sub = int(sub_new.max())
            # Only accept a clean 2-grain split. Splits into 3+ sub-regions
            # almost always mean we're shredding a single irregular grain —
            # leave it alone rather than produce ghost fragments.
            if n_sub != 2:
                continue

            # Write new labels back into the global array
            # First, zero out the original label in this window
            window = new_labels[y1:y2, x1:x2]
            window[window == label_id] = 0

            # Re-use label_id for first sub-region; allocate new IDs for the rest
            sub_ids = list(range(1, n_sub + 1))
            reuse_id = label_id
            for j, sid in enumerate(sub_ids):
                new_id = reuse_id if j == 0 else next_id
                if j > 0:
                    next_id += 1
                window[sub_new == sid] = new_id

            n_split += 1
            logger.info(
                f"Grain #{m.grain_index} (label {label_id}) → "
                f"{n_sub} sub-regions (tight_dist={tight_dist})"
            )

        logger.info(
            f"Re-segmentation: {len(flagged)} flagged, {n_split} successfully split"
        )
        return new_labels

    @staticmethod
    def _load(image_bytes: bytes) -> np.ndarray:
        arr = np.frombuffer(image_bytes, dtype=np.uint8)
        bgr = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if bgr is None:
            raise ValueError("Could not decode image — unsupported format or corrupted file")
        return bgr

    @staticmethod
    def _to_grayscale(bgr: np.ndarray) -> np.ndarray:
        return cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)

    @staticmethod
    def _blur(gray: np.ndarray, kernel: int) -> np.ndarray:
        k = kernel if kernel % 2 == 1 else kernel + 1
        return cv2.GaussianBlur(gray, (k, k), 0)

    @staticmethod
    def _threshold(
        blurred: np.ndarray, block_size: int, c: int,
        invert: bool, use_global: bool = False,
    ) -> np.ndarray:
        if use_global:
            thresh_val, _ = cv2.threshold(blurred, 0, 255, cv2.THRESH_OTSU)
            if invert:
                # Scanner: grain tips are dimmer than centre — drop threshold to
                # 75% of Otsu so tip pixels are included as foreground.
                lower_thresh = max(1, int(thresh_val * 0.75))
            else:
                # Camera (dark bg, bright grains): use full Otsu so shadow pixels
                # in the gap between touching grains stay as background.
                lower_thresh = thresh_val
            _, binary = cv2.threshold(blurred, lower_thresh, 255, cv2.THRESH_BINARY)
            return cv2.bitwise_not(binary) if invert else binary

        thresh_type = cv2.THRESH_BINARY_INV if invert else cv2.THRESH_BINARY
        bs = block_size if block_size % 2 == 1 else block_size + 1
        return cv2.adaptiveThreshold(
            blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, thresh_type, bs, c
        )

    @staticmethod
    def _morphology(binary: np.ndarray, kernel_size: int, iterations: int) -> np.ndarray:
        kernel = cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE, (kernel_size, kernel_size)
        )
        # Opening removes small noise blobs
        opened = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel, iterations=iterations)
        # Closing fills small holes inside grains
        closed = cv2.morphologyEx(opened, cv2.MORPH_CLOSE, kernel, iterations=iterations)
        return closed

    @staticmethod
    def _remove_small_components(binary: np.ndarray, min_area: int) -> np.ndarray:
        """Erase connected components smaller than min_area from the binary mask."""
        n, labels, stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)
        if n <= 1:
            return binary
        keep = np.where(stats[1:, cv2.CC_STAT_AREA] >= min_area)[0] + 1
        return np.isin(labels, keep).astype(np.uint8) * 255

    @staticmethod
    def _fill_holes(binary: np.ndarray) -> np.ndarray:
        """Fill interior holes in each grain blob using flood-fill from the border.

        Rough grain texture leaves hollow regions inside each blob, which creates
        multiple distance-transform peaks and causes watershed to split one grain
        into several fragments. Filling the holes gives each grain a single smooth
        peak so watershed assigns it exactly one label.
        """
        from scipy.ndimage import binary_fill_holes
        filled = binary_fill_holes(binary.astype(bool))
        return filled.astype(np.uint8) * 255

    @staticmethod
    def _save_annotated(annotated: np.ndarray, original_filename: str) -> str:
        stem = Path(original_filename).stem
        out_dir = settings.output_dir
        out_dir.mkdir(parents=True, exist_ok=True)
        ts = int(time.time())
        out_path = out_dir / f"{stem}_annotated_{ts}.png"
        cv2.imwrite(str(out_path), annotated)
        logger.debug(f"Annotated image saved to {out_path}")
        return str(out_path)
