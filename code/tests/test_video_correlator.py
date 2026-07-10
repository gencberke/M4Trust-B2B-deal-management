from backend.app.services.video.correlator import correlate
from backend.app.services.video.interfaces import Detection


def box(x, y, w=100, h=100, class_name="cardboard box", confidence=0.9):
    return Detection(class_name=class_name, confidence=confidence, x=x, y=y, width=w, height=h)


def test_damage_inside_box_is_attached_to_it():
    boxes = [box(100, 100)]
    damages = [box(100, 100, w=10, h=10, class_name="hole", confidence=0.5)]

    result = correlate(boxes, damages)

    assert len(result.boxes) == 1
    assert len(result.boxes[0].damages) == 1
    assert result.unmatched_damages == []


def test_damage_outside_any_box_is_unmatched():
    boxes = [box(100, 100)]
    damages = [box(900, 900, w=10, h=10, class_name="hole", confidence=0.5)]

    result = correlate(boxes, damages)

    assert result.boxes[0].damages == []
    assert len(result.unmatched_damages) == 1


def test_non_countable_classes_are_dropped():
    boxes = [box(100, 100, class_name="Person"), box(200, 200, class_name="cardboard box")]

    result = correlate(boxes, [])

    assert len(result.boxes) == 1
    assert result.boxes[0].box.class_name == "cardboard box"


def test_damage_can_match_multiple_overlapping_boxes():
    boxes = [box(100, 100, w=200, h=200), box(120, 120, w=200, h=200)]
    damages = [box(110, 110, w=5, h=5, class_name="wet", confidence=0.4)]

    result = correlate(boxes, damages)

    assert len(result.boxes[0].damages) == 1
    assert len(result.boxes[1].damages) == 1
    assert result.unmatched_damages == []


def test_no_boxes_and_no_damages_returns_empty_result():
    result = correlate([], [])
    assert result.boxes == []
    assert result.unmatched_damages == []
