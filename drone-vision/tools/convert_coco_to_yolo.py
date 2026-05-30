#!/usr/bin/env python3
"""Convert a Roboflow COCO object-detection export into YOLO directory format."""

from __future__ import annotations

import argparse
import json
import shutil
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any


IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


@dataclass(frozen=True)
class ConversionSummary:
    train_images: int
    val_images: int
    annotations: int
    classes: list[str]


def convert_coco_to_yolo(
    *,
    source_dir: Path,
    output_dir: Path,
    val_prefix: str = "pos_G2",
    overwrite: bool = False,
    copy_images: bool = False,
) -> ConversionSummary:
    annotation_path = source_dir / "_annotations.coco.json"
    if not annotation_path.exists():
        raise FileNotFoundError(f"Missing COCO annotations: {annotation_path}")

    if output_dir.exists():
        if not overwrite:
            raise FileExistsError(f"Output directory exists: {output_dir}")
        shutil.rmtree(output_dir)

    data = json.loads(annotation_path.read_text(encoding="utf-8"))
    images = {int(image["id"]): image for image in data.get("images", [])}
    categories = _collapsed_categories(data.get("categories", []))
    annotations_by_image: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for annotation in data.get("annotations", []):
        annotations_by_image[int(annotation["image_id"])].append(annotation)

    class_names = sorted(set(categories.values()))
    class_to_index = {name: index for index, name in enumerate(class_names)}

    counts = {"train": 0, "val": 0}
    annotation_count = 0
    for image_id, image in images.items():
        file_name = image["file_name"]
        split = "val" if file_name.startswith(val_prefix) else "train"
        image_source = source_dir / file_name
        if not image_source.exists() or image_source.suffix.lower() not in IMAGE_SUFFIXES:
            raise FileNotFoundError(f"Missing image referenced by COCO file: {image_source}")

        image_target = output_dir / "images" / split / file_name
        label_target = output_dir / "labels" / split / f"{Path(file_name).stem}.txt"
        image_target.parent.mkdir(parents=True, exist_ok=True)
        label_target.parent.mkdir(parents=True, exist_ok=True)

        _materialize_image(image_source, image_target, copy_images=copy_images)

        label_lines = []
        width = float(image["width"])
        height = float(image["height"])
        for annotation in annotations_by_image.get(image_id, []):
            category_name = categories.get(int(annotation["category_id"]))
            if category_name is None:
                continue
            yolo_box = _coco_bbox_to_yolo(annotation["bbox"], width=width, height=height)
            label_lines.append(f"{class_to_index[category_name]} " + " ".join(f"{v:.6f}" for v in yolo_box))
            annotation_count += 1

        label_target.write_text("\n".join(label_lines) + ("\n" if label_lines else ""), encoding="utf-8")
        counts[split] += 1

    _write_data_yaml(output_dir, class_names)
    return ConversionSummary(
        train_images=counts["train"],
        val_images=counts["val"],
        annotations=annotation_count,
        classes=class_names,
    )


def _collapsed_categories(categories: list[dict[str, Any]]) -> dict[int, str]:
    mapping: dict[int, str] = {}
    for category in categories:
        name = str(category["name"]).strip().lower()
        if not name:
            continue
        mapping[int(category["id"])] = name
    if not mapping:
        raise ValueError("COCO file has no usable categories")
    return mapping


def _coco_bbox_to_yolo(bbox: list[float], *, width: float, height: float) -> tuple[float, float, float, float]:
    if len(bbox) != 4:
        raise ValueError(f"Invalid COCO bbox: {bbox}")
    x, y, box_width, box_height = [float(value) for value in bbox]
    if width <= 0 or height <= 0 or box_width <= 0 or box_height <= 0:
        raise ValueError(f"Invalid bbox/image dimensions: bbox={bbox}, width={width}, height={height}")

    center_x = (x + box_width / 2) / width
    center_y = (y + box_height / 2) / height
    normalized_width = box_width / width
    normalized_height = box_height / height
    return tuple(_clamp01(value) for value in (center_x, center_y, normalized_width, normalized_height))


def _clamp01(value: float) -> float:
    return min(1.0, max(0.0, value))


def _materialize_image(source: Path, target: Path, *, copy_images: bool) -> None:
    if copy_images:
        shutil.copy2(source, target)
        return
    target.symlink_to(source)


def _write_data_yaml(output_dir: Path, class_names: list[str]) -> None:
    names = ", ".join(repr(name) for name in class_names)
    content = (
        f"path: {output_dir.resolve()}\n"
        "train: images/train\n"
        "val: images/val\n"
        f"nc: {len(class_names)}\n"
        f"names: [{names}]\n"
    )
    (output_dir / "data.yaml").write_text(content, encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True, help="COCO split directory with _annotations.coco.json.")
    parser.add_argument("--output", type=Path, required=True, help="Output YOLO dataset directory.")
    parser.add_argument(
        "--val-prefix",
        default="pos_G2",
        help="Image filename prefix to hold out as validation. Default: pos_G2.",
    )
    parser.add_argument("--overwrite", action="store_true", help="Replace an existing output directory.")
    parser.add_argument("--copy-images", action="store_true", help="Copy images instead of creating symlinks.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    summary = convert_coco_to_yolo(
        source_dir=args.source,
        output_dir=args.output,
        val_prefix=args.val_prefix,
        overwrite=args.overwrite,
        copy_images=args.copy_images,
    )
    print(
        f"Converted {summary.train_images} train images, {summary.val_images} val images, "
        f"{summary.annotations} annotations, classes={summary.classes}"
    )
    print(f"data.yaml: {args.output / 'data.yaml'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
