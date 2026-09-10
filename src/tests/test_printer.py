import pytest
from unittest.mock import patch, MagicMock

def test_print_calls_lp_on_mac(tmp_path):
    jpeg = tmp_path / "photo.jpg"
    from PIL import Image
    Image.new("RGB", (900, 600), (200, 100, 50)).save(str(jpeg), "JPEG")

    with patch("printer.platform.system", return_value="Darwin"), \
         patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        from printer import print_image
        print_image(str(jpeg), printer_name="TestPrinter", copies=2)
        assert mock_run.call_count == 2
        args = mock_run.call_args_list[0][0][0]
        assert "lp" in args
        assert "-d" in args
        assert "TestPrinter" in args

def test_print_raises_on_lp_failure(tmp_path):
    jpeg = tmp_path / "photo.jpg"
    from PIL import Image
    Image.new("RGB", (900, 600)).save(str(jpeg), "JPEG")

    with patch("printer.platform.system", return_value="Darwin"), \
         patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1, stderr="error")
        from printer import print_image
        with pytest.raises(RuntimeError, match="Print failed"):
            print_image(str(jpeg), printer_name="TestPrinter", copies=1)
