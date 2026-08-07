import sys
import gc
import numpy as np
import soundfile as sf
import pyloudnorm as pyln
from scipy.signal import butter, sosfiltfilt, lfilter
from pedalboard import (
    Pedalboard, Compressor, HighpassFilter, HighShelfFilter, 
    LowShelfFilter, Gain, PeakFilter, Distortion, NoiseGate, LowpassFilter
)

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
    from .mastering_finalizer import finalize_true_peak
except ImportError:
    from mastering_finalizer import finalize_true_peak

def split_bands(signal: np.ndarray, sample_rate: float, low_cutoff: float = 120.0, high_cutoff: float = 5000.0):
    """
    Divide o canal de áudio em 3 de forma limpa com fase linear zero.
    """
    sos_low = butter(2, low_cutoff, btype='low', fs=sample_rate, output='sos')
    low_band = sosfiltfilt(sos_low, signal)
    
    sos_high = butter(2, high_cutoff, btype='high', fs=sample_rate, output='sos')
    high_band = sosfiltfilt(sos_high, signal)
    
    mid_band = signal - low_band - high_band
    
    return low_band.astype(np.float32), mid_band.astype(np.float32), high_band.astype(np.float32)

def restore_transients(signal: np.ndarray, crest_factor: float, sample_rate: float, faccao: str):
    """
    MÓDULO TRANSIENTE ADAPTATIVO EXTREMAMENTE RÁPIDO:
    Se a track for ultra-densa e saturada (Hard Techno/Schranz), desativamos o boost
    para evitar acúmulo de cliques digitais e distorção no limitador [1.2].
    """
    if (faccao == "red" and crest_factor < 6.5) or crest_factor >= 8.5:
        return signal
        
    abs_signal = np.abs(signal)
    
    time_constant = 0.005
    alpha = 1.0 - np.exp(-1.0 / (time_constant * sample_rate))
    
    b = [alpha]
    a = [1.0, -(1.0 - alpha)]
    envelope = lfilter(b, a, abs_signal)
    
    derivative = np.diff(envelope, prepend=0)
    derivative = np.maximum(0, derivative)  
    
    max_deriv = np.max(derivative) + 1e-9
    normalized_transients = derivative / max_deriv
    
    boost_val = 0.15 if faccao == "blue" else 0.08
    boost_factor = 1.0 + boost_val * normalized_transients
    return (signal * boost_factor).astype(np.float32)

def saturate_side(side_channel: np.ndarray, sample_rate: float):
    """
    SATURAÇÃO HARMÔNICA: Saturação suave não-linear (tangente hiperbólica).
    """
    sos_hp = butter(2, 5000.0, btype='high', fs=sample_rate, output='sos')
    side_highs = sosfiltfilt(sos_hp, side_channel)
    
    drive = 1.15
    saturated_highs = np.tanh(side_highs * drive) / drive
    
    return (side_channel - side_highs + saturated_highs).astype(np.float32)

def masterize(input_path: str, output_path: str, estilo: str, intensidade: str, is_preview: bool = False):
    validated_input = validate_mastering_request(input_path, output_path)
    input_path = str(validated_input.input_path)
    output_path = str(validated_input.output_path)
    temporary_output_path = None
    pre_finalizer_path = None

    try:
        # 1. LEITURA SELETIVA E ULTRA-RÁPIDA (ZLP - Zero Latency Preview) [1]
        if is_preview:
            info = sf.info(input_path) 
            sample_rate = info.samplerate
            total_frames = info.frames
            
            preview_frames = int(15.0 * sample_rate)
            
            if total_frames > preview_frames:
                start_frame = int(total_frames / 2) - int(preview_frames / 2)
            else:
                start_frame = 0
                preview_frames = total_frames
                
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
        
        if initial_lufs > -14.0:
            pre_gain_value = 0.0
            audio_data = Pedalboard([NoiseGate(threshold_db=-55.0, ratio=2.5, attack_ms=2.0, release_ms=200.0)])(audio_data, sample_rate)
        else:
            pre_gain_value = -14.0 - initial_lufs
            pre_gain_value = min(8.0, max(-8.0, pre_gain_value))
            gate_and_norm = Pedalboard([
                NoiseGate(threshold_db=-55.0, ratio=2.5, attack_ms=2.0, release_ms=200.0),
                Gain(gain_db=pre_gain_value)
            ])
            audio_data = gate_and_norm(audio_data, sample_rate)

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

        # 6. MATRIZ MID/SIDE E PROCESSADORES DE SINAL INTEGRAIS
        L = audio_data[0, :]
        R = audio_data[1, :]
        mid = ((L + R) * 0.5).astype(np.float32)
        side = ((L - R) * 0.5).astype(np.float32)
        
        mid = restore_transients(mid, crest_factor_db, sample_rate, faccao)
        side = saturate_side(side, sample_rate)
        
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
        
        if faccao == "red" and crest_factor_db < 7.5:
            hf_cutoff = 13800.0  
            clean_highs = Pedalboard([
                LowpassFilter(cutoff_frequency_hz=hf_cutoff),
                PeakFilter(cutoff_frequency_hz=4500.0, gain_db=-1.5, q=2.0), 
                PeakFilter(cutoff_frequency_hz=6500.0, gain_db=-2.5, q=1.5), 
                PeakFilter(cutoff_frequency_hz=8000.0, gain_db=-1.5, q=1.0)
            ])
        else:
            hf_cutoff = 15500.0
            clean_highs = Pedalboard([
                LowpassFilter(cutoff_frequency_hz=hf_cutoff),
                PeakFilter(cutoff_frequency_hz=6500.0, gain_db=-2.0, q=1.5),
                PeakFilter(cutoff_frequency_hz=4500.0, gain_db=-1.0, q=2.0)
            ])
            
        mid_high_filtered = clean_highs(mid_high[np.newaxis, :], sample_rate)[0]
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
        # Blue Team mantém o estéreo amplo. Red Team blinda as laterais contra chiados de fase em 13.5kHz [1.2.2].
        board_side = Pedalboard([
            HighpassFilter(cutoff_frequency_hz=150.0),
            LowpassFilter(cutoff_frequency_hz=13500.0 if faccao == "red" else 15000.0)
        ])
        
        rms_side_db = get_band_rms_db(side)
        
        # Desativa a compressão dinâmica no Side se for track industrial de alta densidade
        # para evitar que o "sopro/chiado de fase" do Suno seja amplificado nas laterais [1.2.2]
        if faccao == "red" and crest_factor_db < 7.5:
            board_side.append(Gain(gain_db=0.2)) # Apenas uma abertura estática sutil e limpa
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

        # 11. ESTÁGIO DE COMPENSAÇÃO DE GANHO FINAL E LIMITADOR (TRUE PEAK OVERSAMPLING 4X)
        audio_for_meter = audio_reconstructed.T
        current_lufs = meter.integrated_loudness(audio_for_meter)
        
        gain_needed = target_lufs - current_lufs

        # Impede que o limitador final trabalhe duro em picos
        if gain_needed > 5.0:
            pre_boost = gain_needed - 3.0
            audio_reconstructed = Pedalboard([Gain(gain_db=pre_boost)])(audio_reconstructed, sample_rate)
            gain_needed = 3.0

        # Gain compensation remains in Python. The final peak stage is rendered
        # externally and verified on the saved PCM24 file.
        final_audio = Pedalboard([
            Gain(gain_db=gain_needed)
        ])(audio_reconstructed, sample_rate).T

        # 12. VERIFIED TRUE PEAK FINALIZER + ATOMIC PUBLICATION
        pre_finalizer_path = create_temporary_output_path(output_path)
        temporary_output_path = create_temporary_output_path(output_path)

        sf.write(
            str(pre_finalizer_path),
            final_audio,
            sample_rate,
            format='WAV',
            subtype='FLOAT',
        )

        finalizer_result = finalize_true_peak(
            pre_finalizer_path,
            temporary_output_path,
            ceiling_dbtp=limiter_ceiling,
            release_ms=limiter_release,
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
        print(f"SUCESSO|{gain_needed + pre_gain_value:.2f}|{target_lufs:.1f}_LUFS|{tipo_processo}|{crest_factor_db:.2f}dB_Dinâmica|Teto_{limiter_ceiling:.1f}dBTP")

    except Exception:
        cleanup_temporary_output(pre_finalizer_path)
        cleanup_temporary_output(temporary_output_path)
        raise


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
