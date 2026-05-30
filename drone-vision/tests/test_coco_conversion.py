import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from tools.convert_coco_to_yolo import convert_coco_to_yolo


class CocoConversionTests(unittest.TestCase):
    def test_convert_coco_to_yolo_collapses_duplicate_drone_classes_and_splits_by_prefix(self) -> None:
        with TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "coco" / "train"
            output = Path(tmpdir) / "yolo"
            source.mkdir(parents=True)
            (source / "pos_G3P1.jpg").write_bytes(b"fake")
            (source / "pos_G2P1.jpg").write_bytes(b"fake")
            coco = {
                "images": [
                    {"id": 10, "file_name": "pos_G3P1.jpg", "width": 100, "height": 50},
                    {"id": 20, "file_name": "pos_G2P1.jpg", "width": 100, "height": 50},
                ],
                "categories": [
                    {"id": 0, "name": "drone"},
                    {"id": 1, "name": "drone"},
                ],
                "annotations": [
                    {"id": 1, "image_id": 10, "category_id": 1, "bbox": [10, 5, 20, 10]},
                    {"id": 2, "image_id": 20, "category_id": 1, "bbox": [40, 10, 10, 20]},
                ],
            }
            (source / "_annotations.coco.json").write_text(json.dumps(coco), encoding="utf-8")

            summary = convert_coco_to_yolo(source_dir=source, output_dir=output)

            self.assertEqual(summary.train_images, 1)
            self.assertEqual(summary.val_images, 1)
            self.assertEqual(summary.annotations, 2)
            self.assertEqual(summary.classes, ["drone"])
            self.assertTrue((output / "images" / "train" / "pos_G3P1.jpg").is_symlink())
            train_label = (output / "labels" / "train" / "pos_G3P1.txt").read_text(encoding="utf-8").strip()
            val_label = (output / "labels" / "val" / "pos_G2P1.txt").read_text(encoding="utf-8").strip()
            self.assertEqual(train_label, "0 0.200000 0.200000 0.200000 0.200000")
            self.assertEqual(val_label, "0 0.450000 0.400000 0.100000 0.400000")
            self.assertIn("names: ['drone']", (output / "data.yaml").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
