"""The labels of what cameras detect, in one place.

Every source of detections speaks its own words: Reolink's AI says `people` and `dog_cat`,
Hikvision says `VMD` and `human`, Norn's own detector knows COCO's 80 classes. Norn maps all of
them onto these few labels, so a trigger means the same on every camera, and the web app shows
the same names everywhere (GET /api/labels).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Annotated, Any

from pydantic import AfterValidator


@dataclass(frozen=True)
class Label:
    id: str
    name: str
    description: str


LABELS: dict[str, Label] = {
    label.id: label
    for label in (
        Label("motion", "Motion", "Something moved in the picture."),
        Label("person", "Person", "A person."),
        Label("vehicle", "Vehicle", "A car, truck, bus, motorcycle or bicycle."),
        Label("animal", "Animal", "A pet or another animal."),
        Label("face", "Face", "A face, from cameras that detect faces."),
        Label("package", "Package", "A parcel left at the door."),
        Label("doorbell", "Doorbell", "Someone rang a video doorbell."),
    )
}


def check_label(value: str) -> str:
    if value not in LABELS:
        raise ValueError(f"{value!r} is not one of {', '.join(LABELS)}")
    return value


# A label in config.yaml or an API body.
LabelId = Annotated[str, AfterValidator(check_label)]


def describe() -> list[dict[str, Any]]:
    return [asdict(label) for label in LABELS.values()]


# The words of each source, onto the labels.

REOLINK_AI = {
    "people": "person",
    "person": "person",
    "vehicle": "vehicle",
    "dog_cat": "animal",
    "pet": "animal",
    "face": "face",
    "package": "package",
}

# Hikvision ISAPI <eventType>: VMD is plain motion detection, the others are "smart" events,
# which may say what they saw in <targetType> (HIKVISION_TARGETS).
HIKVISION_EVENTS = {
    "vmd": "motion",
    "fielddetection": "motion",
    "linedetection": "motion",
    "regionentrance": "motion",
    "regionexiting": "motion",
}
HIKVISION_TARGETS = {"human": "person", "vehicle": "vehicle"}

# COCO class numbers (Norn's own object detector).
COCO = {
    0: "person",
    **dict.fromkeys((1, 2, 3, 5, 7), "vehicle"),  # bicycle, car, motorcycle, bus, truck
    **dict.fromkeys(range(14, 24), "animal"),  # bird, cat, dog, horse, sheep, cow, ...
}
