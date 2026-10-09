"""
Tests for WhatsApp Meta Cloud API Alert Service (Owner Only Isolation)
"""

import pytest
from unittest.mock import patch, MagicMock
from ui.whatsapp_service import WhatsAppService


@pytest.fixture
def mock_whatsapp():
    with patch("ui.whatsapp_service.settings") as mock_settings:
        mock_settings.WHATSAPP_PHONE_NUMBER_ID = "1239464059243498"
        mock_settings.META_ACCESS_TOKEN = "test_meta_token"
        mock_settings.OWNER_ALERT_PHONE = "+918421077613"
        svc = WhatsAppService()
        return svc


def test_clean_phone_formatting(mock_whatsapp):
    assert mock_whatsapp._clean_phone("+918421077613") == "918421077613"
    assert mock_whatsapp._clean_phone("8421077613") == "918421077613"
    assert mock_whatsapp._clean_phone("+91 84210-77613") == "918421077613"


def test_strictly_isolated_to_owner(mock_whatsapp):
    assert mock_whatsapp.owner_phone == "918421077613"


def test_send_owner_alert_payload(mock_whatsapp):
    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"messages": [{"id": "wamid.test123"}]}'
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        success = mock_whatsapp.send_owner_alert("Test alert message", sync=True)
        assert success is True

        # Verify URL request
        req = mock_urlopen.call_args[0][0]
        assert "1239464059243498" in req.full_url
        assert req.get_header("Authorization") == "Bearer test_meta_token"
        assert b'"to": "918421077613"' in req.data


def test_notify_trade_open_structure(mock_whatsapp):
    with patch.object(mock_whatsapp, "send_owner_alert") as mock_send:
        pos = MagicMock()
        pos.symbol = "BTCUSDT"
        pos.side = "LONG"
        pos.entry_price = 82400.0
        pos.size = 0.05
        pos.leverage = 10
        pos.sl_price = 81200.0
        pos.tp1_price = 84800.0
        pos.tp2_price = 86000.0

        mock_whatsapp.notify_trade_open(pos, 88.5, "BULLISH_TREND", "EMA Confluence")
        assert mock_send.called
        call_text = mock_send.call_args[0][0]
        assert "BTCUSDT" in call_text
        assert "LONG" in call_text
        assert "Satnam ji" in call_text


def test_notify_panic_structure(mock_whatsapp):
    with patch.object(mock_whatsapp, "send_owner_alert") as mock_send:
        mock_whatsapp.notify_panic(3)
        assert mock_send.called
        call_text = mock_send.call_args[0][0]
        assert "EMERGENCY FLATTEN" in call_text
        assert "Closed Positions: 3" in call_text
