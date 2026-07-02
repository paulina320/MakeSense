import numpy as np

from processing.rendering import boundary_crossfade_gains, make_boundary_crossfade_loop


def test_half_hann_crossfade_has_constant_collaborative_amplitude():
    fade_out, fade_in = boundary_crossfade_gains(200, "half_hann")

    assert np.allclose(fade_out + fade_in, 1.0, atol=1e-6)
    assert np.isclose(fade_out[100], 0.5, atol=1e-6)
    assert np.isclose(fade_in[100], 0.5, atol=1e-6)


def test_full_hann_overlap_uses_half_length_cycle_and_constant_gain():
    source = np.full(4000, 0.37, dtype=np.float32)

    loop = make_boundary_crossfade_loop(source, 10_000, 20, "full_hann_50")

    assert len(loop) == 2000
    assert np.allclose(loop, source[0], atol=1e-6)


def test_full_hann_overlap_softens_a_discontinuous_repeat():
    source = np.linspace(-1.0, 1.0, 4000, dtype=np.float32)

    loop = make_boundary_crossfade_loop(source, 10_000, 20, "full_hann_50")

    raw_jump = abs(float(source[0] - source[-1]))
    smoothed_jump = abs(float(loop[0] - loop[-1]))
    assert smoothed_jump < raw_jump * 0.01


def test_equal_power_crossfade_has_constant_collaborative_power():
    fade_out, fade_in = boundary_crossfade_gains(200, "equal_power")

    assert np.allclose(fade_out**2 + fade_in**2, 1.0, atol=1e-6)


def test_short_crossfade_preserves_middle_and_shortens_only_by_overlap():
    source = np.arange(4000, dtype=np.float32)

    loop = make_boundary_crossfade_loop(source, 10_000, 20, "half_hann")

    assert len(loop) == 3800
    assert np.array_equal(loop[:3600], source[200:3800])


def test_short_crossfade_softens_a_discontinuous_repeat():
    source = np.linspace(-1.0, 1.0, 4000, dtype=np.float32)

    loop = make_boundary_crossfade_loop(source, 10_000, 20, "half_hann")

    raw_jump = abs(float(source[0] - source[-1]))
    smoothed_jump = abs(float(loop[0] - loop[-1]))
    assert smoothed_jump < raw_jump * 0.01


def test_off_keeps_original_signal_unchanged():
    source = np.linspace(-1.0, 1.0, 17, dtype=np.float32)

    loop = make_boundary_crossfade_loop(source, 10_000, 20, "off")

    assert np.array_equal(loop, source)
