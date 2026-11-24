from email.message import Message

import pytest
from starlette.responses import Response

from app.presentation.api.v1.download_headers import attachment_disposition


@pytest.mark.parametrize(
    "filename",
    ["rooming_list_hotel.xlsx", "rooming_list_東京ホテル.xlsx", "résumé.pdf", 'report"name.xlsx'],
)
def test_attachment_names_round_trip_through_http_serialization(filename):
    response = Response(headers={"Content-Disposition": attachment_disposition(filename)})
    raw_header = dict(response.raw_headers)[b"content-disposition"]
    assert raw_header.isascii()
    message = Message()
    message["Content-Disposition"] = raw_header.decode("ascii")
    assert message.get_filename() == filename


def test_ascii_attachment_contract_is_preserved():
    assert attachment_disposition("rooming_list_Grand_Hotel.xlsx") == (
        'attachment; filename="rooming_list_Grand_Hotel.xlsx"'
    )


def test_control_characters_cannot_add_response_headers():
    response = Response(
        headers={"Content-Disposition": attachment_disposition("report\r\nX-Forged: yes.xlsx")}
    )
    assert "x-forged" not in response.headers
    assert all(b"\r" not in value and b"\n" not in value for _, value in response.raw_headers)
