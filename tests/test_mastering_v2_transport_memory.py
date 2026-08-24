from pathlib import Path


SOURCE = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "controllers"
    / "mastering-v2.js"
)


def test_mastering_v2_s3_upload_does_not_buffer_full_master_in_memory():
    source = SOURCE.read_text(encoding="utf-8")

    assert "fs.readFileSync(outputPath)" not in source
    assert "await fs.promises.stat(outputPath)" in source
    assert "fs.createReadStream(outputPath)" in source
    assert "Body: outputStream" in source
    assert "ContentLength: outputStat.size" in source
    assert "outputStream.destroy()" in source
