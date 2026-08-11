import sys
import os
import argparse
import json
import logging  
import gc  # 🟢 Importado para viabilizar a limpeza de memória gc.collect() [11]
import numpy as np
import soundfile as sf
import pyloudnorm as pyln
from scipy.signal import butter, sosfiltfilt, lfilter, resample_poly
from pedalboard import (
    Pedalboard, Compressor, HighpassFilter, HighShelfFilter, 
    LowShelfFilter, Gain, PeakFilter, Distortion, LowpassFilter
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stderr
)
logger = logging.getLogger("core_dsp_entrypoint")

try:
    from .mastering_validation import (
        cleanup_temporary_output,
        create_temporary_output_path,
        publish_temporary_output,
        validate_audio_samples,
        validate_mastering_request,
        validate_written_output,
    )
except ImportError:
    from mastering_validation import (
        cleanup_temporary_output,
        create_temporary_output_path,
        publish_temporary_output,
        validate_audio_samples,
        validate_mastering_request,
        validate_written_output,
    )

try:
    from .mastering_loudness import finalize_loudness
except ImportError:
    from mastering_loudness import finalize_loudness


def split_bands(signal: np.ndarray, sample_rate: float, low_cutoff: float = 120.0, high_cutoff: float = 5000.0):
    """Divide o canal de áudio em 3 de forma limpa com fase linear zero [8.4]."""
    sos_low = butter(2, low_cutoff, btype='low', fs=sample_rate, output='sos')
    low_band = sosfiltfilt(sos_low, signal)
    
    sos_high = butter(2, high_cutoff, btype='high', fs=sample_rate, output='sos')
    high_band = sosfiltfilt(sos_high, signal)
    
    mid_band = signal - low_band - high_band
    
    return low_band.astype(np.float32), mid_band.astype(np.float32), high_band.astype(np.float32)


def restore_transients(
    signal: np.ndarray,
    crest_factor: float,
    sample_rate: float,
    faccao: str,
    amount: float = 1.0,
    max_boost_override: float | None = None,
):
    """Aplica o reforço adaptativo local de transientes vetorizado de fase zero [8.8]."""
    amount = float(amount)
    if not np.isfinite(amount) or not 0.0 <= amount <= 1.0:
        raise ValueError("Transient amount must be finite and between 0.0 and 1.0.")

    if max_boost_override is None:
        max_boost = 0.15 if faccao == "blue" else 0.08
        use_legacy_red_low_crest_bypass = faccao == "red"
    else:
        max_boost = float(max_boost_override)
        if not np.isfinite(max_boost) or not 0.0 <= max_boost <= 0.25:
            raise ValueError(
                "Transient max boost override must be finite and between 0.0 and 0.25."
            )
        use_legacy_red_low_crest_bypass = False

    if (
        (use_legacy_red_low_crest_bypass and crest_factor < 6.5)
        or crest_factor >= 8.5
    ):
        return signal

    signal_array = np.asarray(signal, dtype=np.float32)
    if signal_array.size == 0 or amount == 0.0:
        return signal_array.copy()

    abs_signal = np.abs(signal_array.astype(np.float64, copy=False))

    time_constant = 0.005
    alpha = 1.0 - np.exp(-1.0 / (time_constant * sample_rate))

    b = [alpha]
    a = [1.0, -(1.0 - alpha)]
    envelope = lfilter(b, a, abs_signal)

    derivative = np.diff(envelope, prepend=0.0)
    derivative = np.maximum(0.0, derivative)

    epsilon = np.finfo(np.float64).eps
    local_reference = np.maximum(envelope, epsilon)
    normalized_transients = np.divide(
        derivative,
        local_reference,
        out=np.zeros_like(derivative),
        where=local_reference > epsilon,
    )
    normalized_transients = np.clip(normalized_transients, 0.0, 1.0)

    boost_val = max_boost * amount
    boost_factor = 1.0 + boost_val * normalized_transients

    return (signal_array * boost_factor).astype(np.float32)


def saturate_side(
    side_channel: np.ndarray,
    sample_rate: float,
    amount: float = 1.0,
):
    """Aplica saturação lateral de alta frequência imune a aliasing via sobreamostragem 4x [8.6]."""
    amount = float(amount)
    if not np.isfinite(amount) or not 0.0 <= amount <= 1.0:
        raise ValueError("Side saturation amount must be finite and between 0.0 and 1.0.")

    dry = side_channel.astype(np.float64)

    if amount == 0.0:
        return dry.astype(np.float32)

    sos_hp = butter(2, 5000.0, btype='high', fs=sample_rate, output='sos')
    side_highs = sosfiltfilt(sos_hp, side_channel)

    drive = 1.15
    oversample_factor = 4

    side_highs_oversampled = resample_poly(
        side_highs.astype(np.float64),
        oversample_factor,
        1,
        padtype='line',
    )
    saturated_oversampled = (
        np.tanh(side_highs_oversampled * drive) / drive
    )
    saturated_highs = resample_poly(
        saturated_oversampled,
        1,
        oversample_factor,
        padtype='line',
    )

    saturated_highs = saturated_highs[:side_channel.shape[0]]

    wet = (
        dry
        - side_highs.astype(np.float64)
        + saturated_highs
    )

    if amount == 1.0:
        return wet.astype(np.float32)

    return (dry + amount * (wet - dry)).astype(np.float32)


def apply_high_cleanup(
    signal: np.ndarray,
    sample_rate: float,
    faccao: str,
    crest_factor: float,
    amount: float = 1.0,
) -> np.ndarray:
    """Aplica o filtro de limpeza de agudos adaptativo com interpolação linear [10]."""
    amount = float(amount)
    if not np.isfinite(amount) or not 0.0 <= amount <= 1.0:
        raise ValueError(
            "High cleanup amount must be finite and between 0.0 and 1.0."
        )

    signal_array = np.asarray(signal, dtype=np.float32)

    if signal_array.size == 0 or amount == 0.0:
        return signal_array.copy()

    if faccao == "red" and crest_factor < 7.5:
        clean_highs = Pedalboard([
            LowpassFilter(cutoff_frequency_hz=13800.0),
            PeakFilter(cutoff_frequency_hz=4500.0, gain_db=-1.5, q=2.0),
            PeakFilter(cutoff_frequency_hz=6500.0, gain_db=-2.5, q=1.5),
            PeakFilter(cutoff_frequency_hz=8000.0, gain_db=-1.5, q=1.0),
        ])
    else:
        clean_highs = Pedalboard([
            LowpassFilter(cutoff_frequency_hz=15500.0),
            PeakFilter(cutoff_frequency_hz=6500.0, gain_db=-2.0, q=1.5),
            PeakFilter(cutoff_frequency_hz=4500.0, gain_db=-1.0, q=2.0),
        ])

    wet = clean_highs(
        signal_array[np.newaxis, :],
        sample_rate,
    )[0]

    if amount == 1.0:
        return wet.astype(np.float32, copy=False)

    dry64 = signal_array.astype(np.float64)
    wet64 = wet.astype(np.float64)

    return (
        dry64 + amount * (wet64 - dry64)
    ).astype(np.float32)


def calculate_input_pre_gain_db(initial_lufs: float) -> float:
    """Retorna o pré-ganho de entrada de headroom estável sem gate [8.1]."""
    if not np.isfinite(initial_lufs):
        raise ValueError("Initial LUFS must be finite.")

    if initial_lufs > -14.0:
        return 0.0

    return float(min(8.0, max(-8.0, -14.0 - initial_lufs)))


def masterize(
    input_path: str, 
    output_path: str, 
    estilo: str, 
    intensidade: str, 
    is_preview: bool = False, 
    target_lufs_override: float | None = None, 
    limiter_ceiling_override: float | None = None, 
    side_saturation_amount: float = 1.0, 
    transient_amount: float = 1.0, 
    transient_max_boost_override: float | None = None, 
    side_lowpass_cutoff_override: float | None = None, 
    high_cleanup_amount: float = 1.0
):
    """Orquestrador do motor de masterização adaptativa de elite [12]."""
    validated_input = validate_mastering_request(input_path, output_path)
    input_path = str(validated_input.input_path)
    output_path = str(validated_input.output_path)
    temporary_output_path = None
    pre_finalizer_path = None

    # 🟢 Rastreamento dinâmico e seguro de frames de prévia para o ZLP [11]
    if is_preview:
        info = sf.info(input_path)
        duration_samples = info.frames
        sample_rate = info.samplerate
        preview_frames = int(15 * sample_rate)
        if duration_samples > preview_frames:
            start_frame = (duration_samples - preview_frames) // 2
        else:
            start_frame = 0
            preview_frames = duration_samples
            
        audio_data, sample_rate = sf.read(input_path, start=start_frame, frames=preview_frames, dtype='float32')
    else:
        audio_data, sample_rate = sf.read(input_path, dtype='float32')

    audio_data = validate_audio_samples(
        audio_data,
        expected_channels=validated_input.channels,
    )
        
    if audio_data.ndim == 1:
        audio_data = np.column_stack((audio_data, audio_data))
    elif audio_data.ndim == 2 and audio_data.shape[1] == 1:
        mono_flat = audio_data.squeeze()
        audio_data = np.column_stack((mono_flat, mono_flat))
        
    audio_data = audio_data.T

    # 2. ANÁLISE INICIAL DE LOUDNESS
    meter = pyln.Meter(sample_rate)
    initial_lufs = meter.integrated_loudness(audio_data.T)

    pre_gain_value = calculate_input_pre_gain_db(initial_lufs)
    if abs(pre_gain_value) > 1e-12:
        audio_data = Pedalboard([
            Gain(gain_db=pre_gain_value)
        ])(audio_data, sample_rate)

    # 3. ANÁLISE ADAPTATIVA DSP DE CONTROLE DE PICO
    input_lufs = meter.integrated_loudness(audio_data.T)
    rms = np.sqrt(np.mean(audio_data**2))
    peak = np.max(np.abs(audio_data))
    crest_factor_db = float(20 * np.log10(peak / (rms + 1e-9)))

    # Ratios de segurança para o Suno 5.5
    soft_ratio = 1.15 if crest_factor_db < 8.0 else 1.25

    # 4. MAPEAMENTO DE PERFIS E DECLARAÇÃO DE FACÇÕES SÔNICAS (AUDIO CIVIL WAR) [1]
    perfil = estilo.lower().strip()
    if perfil not in ["thunder", "clear_sky", "clear sky", "sunroof", "aurora"]:
        perfil = "clear_sky"

    faccao = "blue" if perfil in ["clear_sky", "clear sky", "aurora"] else "red"

    # 5. MATRIZ DE INTENSIDADE ESTILO MIXEA ADAPTADA ÀS FACÇÕES (DINÂMICA E VOLUME) [1.2.6]
    int_level = intensidade.lower().strip()

    if int_level == "baixa":
        target_lufs = -12.5 if faccao == "blue" else -11.5
        comp_threshold_modifier = 1.0    
        ratio_multiplier = 0.75          
        limiter_ceiling = -1.0 if faccao == "blue" else -1.8 # 🛡️ RED TEAM FAIL-SAFE
        limiter_release = 150.0          
        
    elif int_level == "alta":
        target_lufs = -8.5 if faccao == "blue" else -8.0  
        comp_threshold_modifier = -2.0   
        ratio_multiplier = 1.25          
        limiter_ceiling = -1.0 if faccao == "blue" else -2.0
        limiter_release = 80.0           
        
    else: # "media"
        target_lufs = -10.5 if faccao == "blue" else -9.5
        comp_threshold_modifier = -0.5   
        ratio_multiplier = 1.0           
        limiter_ceiling = -1.0 if faccao == "blue" else -1.8 # 🛡️ RED TEAM FAIL-SAFE
        limiter_release = 120.0          

    # 🟢 DEFENSA ACÚSTICA ADICIONAL (Anti-Distortion Density Shield): 
    if faccao == "red" and crest_factor_db < 7.5:
        lufs_penalty = 1.5 if crest_factor_db < 6.5 else 0.5
        target_lufs -= lufs_penalty
        limiter_ceiling = min(limiter_ceiling, -2.0)
        limiter_release = max(limiter_release, 150.0)

    # V2: delivery overrides only. Creative voicing is unchanged here.
    if target_lufs_override is not None:
        target_lufs = float(target_lufs_override)
    if limiter_ceiling_override is not None:
        limiter_ceiling = float(limiter_ceiling_override)

    # 6. MATRIZ MID/SIDE E PROCESSADORES DE SINAL INTEGRAIS
    L = audio_data[0, :]
    R = audio_data[1, :]
    mid = ((L + R) * 0.5).astype(np.float32)
    side = ((L - R) * 0.5).astype(np.float32)
    
    mid = restore_transients(
        mid,
        crest_factor_db,
        sample_rate,
        faccao,
        transient_amount,
        transient_max_boost_override,
    )
    side = saturate_side(side, sample_rate, side_saturation_amount)
    
    hp_mid = Pedalboard([HighpassFilter(cutoff_frequency_hz=30)])
    mid_filtered = hp_mid(mid[np.newaxis, :], sample_rate)[0]

    mid_low, mid_mid, mid_high = split_bands(mid_filtered, sample_rate)

    def get_band_rms_db(band_data):
        rms_val = np.sqrt(np.mean(band_data**2))
        return float(20 * np.log10(rms_val + 1e-9))

    rms_low_db = get_band_rms_db(mid_low)
    rms_mid_db = get_band_rms_db(mid_mid)
    rms_high_db = get_band_rms_db(mid_high)

    # 7. COMPRESSÃO MULTIBANDA ADAPTADA À GUERRA ACÚSTICA (E REDUÇÃO DE TIMING PARA 140BPM+) [1.2]
    final_ratio = max(1.0, soft_ratio * ratio_multiplier) 

    if faccao == "red" and crest_factor_db < 7.5:
        low_release = 45.0
        mid_release = 50.0
        high_release = 20.0
        high_ratio = max(1.2, final_ratio * 1.8) 
    else:
        low_release = 160.0
        mid_release = 150.0
        high_release = 30.0
        high_ratio = max(1.2, final_ratio * 1.2)

    if perfil == "thunder":
        comp_low = Compressor(threshold_db=rms_low_db - 1.0 + comp_threshold_modifier, ratio=max(1.0, final_ratio * 1.1), attack_ms=45.0, release_ms=low_release)
        comp_mid = Compressor(threshold_db=rms_mid_db + comp_threshold_modifier, ratio=max(1.0, final_ratio), attack_ms=25.0, release_ms=mid_release)
        comp_high = Compressor(threshold_db=rms_high_db - 3.0 + comp_threshold_modifier, ratio=high_ratio, attack_ms=1.0, release_ms=high_release)
        
    elif perfil == "clear_sky" or perfil == "clear sky":
        comp_low = Compressor(threshold_db=rms_low_db + comp_threshold_modifier, ratio=max(1.0, final_ratio * 0.9), attack_ms=50.0, release_ms=low_release)
        comp_mid = Compressor(threshold_db=rms_mid_db + comp_threshold_modifier, ratio=max(1.0, final_ratio * 0.8), attack_ms=30.0, release_ms=mid_release)
        comp_high = Compressor(threshold_db=rms_high_db - 3.0 + comp_threshold_modifier, ratio=high_ratio, attack_ms=1.0, release_ms=high_release)
        
    elif perfil == "sunroof":
        comp_low = Compressor(threshold_db=rms_low_db - 1.5 + comp_threshold_modifier, ratio=max(1.0, final_ratio * 1.2), attack_ms=25.0, release_ms=low_release)
        comp_mid = Compressor(threshold_db=rms_mid_db - 1.0 + comp_threshold_modifier, ratio=max(1.0, final_ratio * 1.1), attack_ms=15.0, release_ms=mid_release)
        comp_high = Compressor(threshold_db=rms_high_db - 3.0 + comp_threshold_modifier, ratio=high_ratio, attack_ms=1.0, release_ms=high_release)
        
    elif perfil == "aurora":
        comp_low = Compressor(threshold_db=rms_low_db + comp_threshold_modifier, ratio=max(1.0, final_ratio * 0.8), attack_ms=40.0, release_ms=low_release)
        comp_mid = Compressor(threshold_db=rms_mid_db + comp_threshold_modifier, ratio=max(1.0, final_ratio * 0.8), attack_ms=25.0, release_ms=mid_release)
        comp_high = Compressor(threshold_db=rms_high_db - 3.0 + comp_threshold_modifier, ratio=high_ratio, attack_ms=1.0, release_ms=high_release)

    mid_low_processed = comp_low(mid_low[np.newaxis, :], sample_rate)[0]
    mid_mid_processed = comp_mid(mid_mid[np.newaxis, :], sample_rate)[0]
    
    mid_high_filtered = apply_high_cleanup(
        mid_high,
        sample_rate,
        faccao,
        crest_factor_db,
        high_cleanup_amount,
    )
    mid_high_processed = comp_high(mid_high_filtered[np.newaxis, :], sample_rate)[0]

    # Recombinação
    mid_processed = mid_low_processed + mid_mid_processed + mid_high_processed

    # 9. EQUALIZAÇÃO CORRETIVA SUTIL (Pinceladas leves baseadas no peso de graves)
    bass_intensity = rms_low_db - rms_mid_db 
    board_eq_mid = Pedalboard([])

    if perfil == "thunder":
        gain_low = max(0.0, 0.8 - (bass_intensity * 0.1)) if bass_intensity > 0 else 0.8
        board_eq_mid.append(LowShelfFilter(cutoff_frequency_hz=55.0, gain_db=gain_low))
    elif perfil == "clear_sky" or perfil == "clear sky":
        board_eq_mid.append(PeakFilter(cutoff_frequency_hz=3200.0, gain_db=0.4, q=0.5))
    elif perfil == "sunroof":
        board_eq_mid.append(LowShelfFilter(cutoff_frequency_hz=90.0, gain_db=0.4))
        board_eq_mid.append(HighShelfFilter(cutoff_frequency_hz=6000.0, gain_db=0.3))
    elif perfil == "aurora":
        board_eq_mid.append(LowShelfFilter(cutoff_frequency_hz=100.0, gain_db=0.4))
        board_eq_mid.append(Distortion(drive_db=0.5)) 

    mid_processed = board_eq_mid(mid_processed[np.newaxis, :], sample_rate)[0]

    # 9. PROCESSAMENTO ESPACIAL (SIDE) SEGURO
    if side_lowpass_cutoff_override is None:
        side_lowpass_cutoff_hz = 13500.0 if faccao == "red" else 15000.0
    else:
        side_lowpass_cutoff_hz = float(side_lowpass_cutoff_override)
        if not np.isfinite(side_lowpass_cutoff_hz) or side_lowpass_cutoff_hz <= 0.0:
            raise ValueError(
                "Side low-pass cutoff override must be finite and greater than 0 Hz."
            )

    board_side = Pedalboard([
        HighpassFilter(cutoff_frequency_hz=150.0),
        LowpassFilter(cutoff_frequency_hz=side_lowpass_cutoff_hz)
    ])
    
    rms_side_db = get_band_rms_db(side)
    
    if faccao == "red" and crest_factor_db < 7.5:
        board_side.append(Gain(gain_db=0.2)) 
    else:
        side_comp = Compressor(threshold_db=max(-40.0, rms_side_db - 4.0), ratio=max(1.0, final_ratio * 0.8), attack_ms=30.0, release_ms=150.0)
        board_side.append(side_comp)
        
        if perfil == "clear_sky" or perfil == "clear sky":
            board_side.append(Gain(gain_db=0.6))
        elif perfil == "aurora":
            board_side.append(Gain(gain_db=0.6))
            board_side.append(HighShelfFilter(cutoff_frequency_hz=5000.0, gain_db=0.8)) 

    if np.any(side):
        side_processed = board_side(side[np.newaxis, :], sample_rate)[0]
    else:
        side_processed = np.zeros_like(mid_processed)

    # Reconstrução estéreo
    L_new = mid_processed + side_processed
    R_new = mid_processed - side_processed
    audio_reconstructed = np.vstack((L_new, R_new))

    del L, R, mid, side, mid_filtered, mid_low, mid_mid, mid_high, mid_low_processed, mid_mid_processed, mid_high_processed, L_new, R_new
    gc.collect()

    pre_finalizer_path = create_temporary_output_path(output_path)
    temporary_output_path = create_temporary_output_path(output_path)

    sf.write(
        str(pre_finalizer_path),
        audio_reconstructed.T,
        sample_rate,
        format='WAV',
        subtype='FLOAT',
    )

    loudness_result = finalize_loudness(
        pre_finalizer_path,
        temporary_output_path,
        target_lufs=target_lufs,
        ceiling_dbtp=limiter_ceiling,
        release_ms=limiter_release,
        tolerance_lu=0.2,
    )
    cleanup_temporary_output(pre_finalizer_path)
    pre_finalizer_path = None

    validate_written_output(
        temporary_output_path,
        expected_sample_rate=sample_rate,
        expected_channels=2,
    )
    publish_temporary_output(temporary_output_path, output_path)
    temporary_output_path = None

    tipo_processo = "PREVIEW" if is_preview else "MASTER"
    print(f"SUCESSO|{loudness_result.total_gain_db + pre_gain_value:.2f}|{target_lufs:.1f}_LUFS|{tipo_processo}|{crest_factor_db:.2f}dB_Dinâmica|Teto_{limiter_ceiling:.1f}dBTP")


def main(argv: list[str] | None = None) -> int:
    args = sys.argv if argv is None else argv
    if len(args) < 5:
        print("ERRO|Usage: core_dsp.py INPUT OUTPUT PROFILE INTENSITY [true]")
        return 2

    is_preview = len(args) == 6 and args[5] == "true"

    try:
        masterize(args[1], args[2], args[3], args[4], is_preview)
    except Exception as exc:
        print(f"ERRO|{exc}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())