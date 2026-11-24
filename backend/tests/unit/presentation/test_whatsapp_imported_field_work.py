"""Bound the heading union to its published projection, preserving order and work."""

from app.presentation.api.v1.routes.whatsapp_contact_support import (
    MAX_WHATSAPP_IMPORTED_FIELDS,
    _merge_imported_field_keys,
)


def test_many_distinct_headings_do_not_retain_or_compare_an_unreturned_union(monkeypatch):
    original = _merge_imported_field_keys.__globals__["_excel_field_key"]

    class TrackedKey(str):
        live = peak = comparisons = 0
        __hash__ = str.__hash__

        def __new__(cls, value):
            obj = super().__new__(cls, value)
            cls.live += 1
            cls.peak = max(cls.peak, cls.live)
            return obj

        def __del__(self):
            type(self).live -= 1

        def __eq__(self, other):
            type(self).comparisons += 1
            return super().__eq__(other)

    monkeypatch.setitem(
        _merge_imported_field_keys.__globals__,
        "_excel_field_key",
        lambda raw: TrackedKey(original(raw)),
    )
    headings = [f"Synthetic Heading {index}" for index in range(3_000)]
    result = _merge_imported_field_keys(declared_keys=headings)
    measured_peak, measured_comparisons = TrackedKey.peak, TrackedKey.comparisons
    assert [str(key) for key in result] == [
        f"synthetic_heading_{index}" for index in range(MAX_WHATSAPP_IMPORTED_FIELDS)
    ]
    assert measured_peak <= MAX_WHATSAPP_IMPORTED_FIELDS + 8
    assert measured_comparisons < len(headings) * 4


def test_heading_bound_preserves_existing_declared_conflict_rules_and_full_consumption():
    consumed = []

    def declared():
        for value in ["Name", "source_file", "Custom A", "Phone", "Custom A"]:
            consumed.append(value)
            yield value

    fields = [
        {
            "duplicate_conflicting_fields": "staff_code",
            "staff_code_2": "ALT",
            "staff_code": "FIRST",
            "Email": "synthetic@example.test",
        },
        {"Custom B": "value", "Name": "Synthetic Name"},
    ]
    result = _merge_imported_field_keys(
        ["Passport", "source_row"], declared_keys=declared(), imported_fields=fields
    )
    assert result == [
        "passport_number",
        "name",
        "custom_a",
        "phone_number",
        "staff_code",
        "email",
        "custom_b",
    ]
    assert consumed == ["Name", "source_file", "Custom A", "Phone", "Custom A"]
    many = []

    def capped():
        for index in range(1_000):
            many.append(index)
            yield f"field_{index}"

    assert len(_merge_imported_field_keys(declared_keys=capped())) == MAX_WHATSAPP_IMPORTED_FIELDS
    assert many == list(range(1_000))
