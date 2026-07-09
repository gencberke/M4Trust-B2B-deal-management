from backend.app.services.video.interfaces import Detection


def make_detection(x=100, y=100, width=50, height=40, class_name="cardboard box", confidence=0.9):
    return Detection(class_name=class_name, confidence=confidence, x=x, y=y, width=width, height=height)


def test_bounding_box_edges_computed_from_center_and_size():
    d = make_detection(x=100, y=100, width=50, height=40)
    assert d.left == 75
    assert d.right == 125
    assert d.top == 80
    assert d.bottom == 120


def test_contains_point_true_for_center():
    d = make_detection(x=100, y=100, width=50, height=40)
    assert d.contains_point(100, 100) is True


def test_contains_point_true_on_edge():
    d = make_detection(x=100, y=100, width=50, height=40)
    assert d.contains_point(75, 80) is True


def test_contains_point_false_outside():
    d = make_detection(x=100, y=100, width=50, height=40)
    assert d.contains_point(0, 0) is False


def test_detection_is_immutable():
    d = make_detection()
    try:
        d.confidence = 0.1
        assert False, "Detection frozen olmalı"
    except AttributeError:
        pass
