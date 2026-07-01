from pathlib import Path

import numpy as np

from processing.compensation import Compensator


def test_demo_filtfilt_compensation_changes_signal_without_phase_shift():
    compensator = Compensator(sample_rate=10000)
    example = Path(__file__).parents[1] / "compensation_filters" / "demo_filtfilt_compensation.json"
    compensation = compensator.load_filter(str(example))

    samples = np.zeros(1000, dtype=np.float32)
    samples[500] = 1.0
    filtered = compensator.apply(samples, compensation)

    assert compensation.application_method == "filtfilt"
    assert compensation.name == "Workshop demo – gentle low-pass"
    assert filtered.shape == samples.shape
    assert not np.allclose(filtered, samples)
    assert int(np.argmax(filtered)) == 500


def test_compensation_preview_can_apply_to_current_signal():
    compensator = Compensator(sample_rate=10000)
    example = Path(__file__).parents[1] / "compensation_filters" / "demo_filtfilt_compensation.json"
    compensation = compensator.load_filter(str(example))
    time = np.arange(2000) / 10000.0
    source = np.sin(2 * np.pi * 200 * time) + np.sin(2 * np.pi * 3000 * time)

    filtered = compensator.apply(source, compensation)

    assert np.sqrt(np.mean((filtered - source) ** 2)) > 0.1


def test_filter_can_be_saved_and_loaded_again(tmp_path):
    compensator = Compensator(sample_rate=10000)
    example = Path(__file__).parents[1] / "compensation_filters" / "demo_filtfilt_compensation.json"
    original = compensator.load_filter(str(example))
    saved = tmp_path / "saved_filter.json"

    compensator.save_filter(str(saved), original)
    restored = compensator.load_filter(str(saved))

    assert restored.name == original.name
    assert restored.application_method == original.application_method
    assert np.allclose(restored.filter_coefficients[0], original.filter_coefficients[0])
    assert np.allclose(restored.filter_coefficients[1], original.filter_coefficients[1])
