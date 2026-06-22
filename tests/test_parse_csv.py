import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from main import parse_csv_cars


def test_valid_csv_single_row():
    csv = "road,number,type,color\nBNSF,12345,boxcar,red\n"
    rows, errors = parse_csv_cars(csv)
    assert errors == []
    assert len(rows) == 1
    assert rows[0]["reporting_marks"] == "BNSF"
    assert rows[0]["car_number"] == "12345"
    assert rows[0]["color"] == "red"


def test_missing_reporting_marks_skipped():
    csv = "road,number,type\n,12345,boxcar\n"
    rows, errors = parse_csv_cars(csv)
    assert rows == []
    assert len(errors) == 1
    assert "road" in errors[0]


def test_missing_car_number_skipped():
    csv = "road,number,type\nBNSF,,boxcar\n"
    rows, errors = parse_csv_cars(csv)
    assert rows == []
    assert len(errors) == 1
    assert "number" in errors[0]


def test_empty_content_returns_error():
    rows, errors = parse_csv_cars("")
    assert rows == []
    assert len(errors) == 1
    assert "empty" in errors[0].lower()


def test_car_type_normalised():
    csv = "road,number,type\nBNSF,1,Box Car\n"
    rows, errors = parse_csv_cars(csv)
    assert errors == []
    assert rows[0]["car_type"] == "boxcar"
