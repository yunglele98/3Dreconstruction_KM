"""Tests for scripts/train/ ML training data pipeline."""

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts" / "train"))

from export_coco import label_studio_to_coco, split_dataset


# ── export_coco ──────────────────────────────────────────────────────

def test_label_studio_to_coco_rectangles():
    classes = ["wall", "window", "door"]
    ls_data = [
        {
            "data": {"image": "/data/local-files/?d=images/test.jpg"},
            "annotations": [{
                "result": [
                    {
                        "type": "rectanglelabels",
                        "original_width": 1920,
                        "original_height": 1080,
                        "value": {
                            "x": 10, "y": 20, "width": 30, "height": 40,
                            "rectanglelabels": ["window"],
                        },
                    },
                ],
            }],
        },
    ]

    coco = label_studio_to_coco(ls_data, classes)
    assert len(coco["images"]) == 1
    assert len(coco["annotations"]) == 1
    assert coco["annotations"][0]["category_id"] == 1  # window
    bbox = coco["annotations"][0]["bbox"]
    assert bbox[0] == round(10 / 100 * 1920, 1)  # x in pixels
    assert bbox[2] == round(30 / 100 * 1920, 1)  # width in pixels


def test_label_studio_to_coco_polygons():
    classes = ["wall", "window", "door"]
    ls_data = [
        {
            "data": {"image": "test.jpg"},
            "annotations": [{
                "result": [
                    {
                        "type": "polygonlabels",
                        "original_width": 1000,
                        "original_height": 1000,
                        "value": {
                            "points": [[10, 10], [20, 10], [20, 20], [10, 20]],
                            "polygonlabels": ["door"],
                        },
                    },
                ],
            }],
        },
    ]

    coco = label_studio_to_coco(ls_data, classes)
    assert len(coco["annotations"]) == 1
    assert coco["annotations"][0]["category_id"] == 2  # door
    assert "segmentation" in coco["annotations"][0]


def test_label_studio_unknown_class_ignored():
    classes = ["wall", "window"]
    ls_data = [
        {
            "data": {"image": "test.jpg"},
            "annotations": [{
                "result": [{
                    "type": "rectanglelabels",
                    "original_width": 100,
                    "original_height": 100,
                    "value": {"x": 0, "y": 0, "width": 50, "height": 50,
                              "rectanglelabels": ["spaceship"]},
                }],
            }],
        },
    ]

    coco = label_studio_to_coco(ls_data, classes)
    assert len(coco["annotations"]) == 0


def test_split_dataset():
    coco = {
        "info": {},
        "categories": [{"id": 0, "name": "wall"}],
        "images": [{"id": i, "file_name": f"{i}.jpg", "width": 100, "height": 100}
                    for i in range(10)],
        "annotations": [{"id": i, "image_id": i, "category_id": 0, "bbox": [0, 0, 50, 50], "area": 2500, "iscrowd": 0}
                         for i in range(10)],
    }

    train, val = split_dataset(coco, train_ratio=0.8)
    assert len(train["images"]) == 8
    assert len(val["images"]) == 2
    # Annotations should match their images
    train_ids = {img["id"] for img in train["images"]}
    for ann in train["annotations"]:
        assert ann["image_id"] in train_ids


def test_coco_categories():
    classes = ["wall", "window", "door"]
    coco = label_studio_to_coco([], classes)
    assert len(coco["categories"]) == 3
    assert coco["categories"][0]["name"] == "wall"
    assert coco["categories"][2]["name"] == "door"


# ── prepare_training_data ────────────────────────────────────────────

def test_classes_file():
    from prepare_training_data import CLASSES
    assert len(CLASSES) >= 20
    assert "wall" in CLASSES
    assert "window" in CLASSES
    assert "door" in CLASSES
    assert "roof" in CLASSES
