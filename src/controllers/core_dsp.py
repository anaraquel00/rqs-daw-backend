import sys
import gc
import numpy as np
import soundfile as sf
import pyloudnorm as pyln
from scipy.signal import butter, sosfiltfilt
from pedalboard import (
    Pedalboard, Compressor, HighpassFilter, HighShelfFilter, 
    LowShelfFilter, Limiter, Gain, Resample, PeakFilter, Distortion, NoiseGate, LowpassFilter
)

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

def masterize(input_path: str, output_path: str, estilo: str, intensidade: str, is_preview: bool = False):
    try:
        # 1. LEITURA BLINDADA E OTIMIZADA DE ÁUDIO
        audio_data, sample_rate = sf.read(input_path, dtype='float32')
        
        if audio_data.ndim == 1:
            audio_data = np.column_stack((audio_data, audio_data))
        elif audio_data.ndim == 2 and audio_data.shape[1] == 1:
            mono_flat = audio_data.squeeze()
            audio_data = np.column_stack((mono_flat, mono_flat))
            
        audio_data = audio_data.T

        # 2. ANÁLISE INICIAL DE LOUDNESS (Suno 5.5 Safe Normalization)
        meter = pyln.Meter(sample_rate)
        initial_lufs = meter.integrated_loudness(audio_data.T)
        
        # Se a música do Suno 5.5 já vem pré-masterizada e quente (>-14.0 LUFS),
        # pulamos o ganho de entrada para manter o balanço de dinâmica original!
        if initial_lufs > -14.0:
            pre_gain_value = 0.0
            # NoiseGate limpa chiados de fundo em partes silenciosas
            audio_data = Pedalboard([NoiseGate(threshold_db=-55.0, ratio=2.5, attack_ms=2.0, release_ms=200.0)])(audio_data, sample_rate)
        else:
            pre_gain_value = -14.0 - initial_lufs
            pre_gain_value = min(8.0, max(-8.0, pre_gain_value))
            gate_and_norm = Pedalboard([
                NoiseGate(threshold_db=-55.0, ratio=2.5, attack_ms=2.0, release_ms=200.0),
                Gain(gain_db=pre_gain_value)
            ])
            audio_data = gate_and_norm(audio_data, sample_rate)

        # 3. MOTOR DE PREVIEW (Corte de 15s)
        if is_preview:
            total_samples = audio_data.shape[1]
            total_duration_sec = total_samples / sample_rate
            if total_duration_sec > 15.0:
                start_sec = (total_duration_sec / 2.0) - 7.5
                end_sec = start_sec + 15.0
                audio_data = audio_data[:, int(start_sec * sample_rate):int(end_sec * sample_rate)]

        # 4. ANÁLISE ADAPTATIVA DSP DE CONTROLE DE PICO
        input_lufs = meter.integrated_loudness(audio_data.T)
        rms = np.sqrt(np.mean(audio_data**2))
        peak = np.max(np.abs(audio_data))
        crest_factor_db = float(20 * np.log10(peak / (rms + 1e-9)))

        # Ratios de segurança para o Suno 5.5
        soft_ratio = 1.15 if crest_factor_db < 8.0 else 1.25

        # 5. MAPEAMENTO DE PERFIS DE MODELAGEM ACÚSTICA (ESTILOS)
        perfil = estilo.lower().strip()
        if perfil not in ["thunder", "clear_sky", "clear sky", "sunroof", "aurora"]:
            perfil = "clear_sky"

        # 6. MATRIZ DE INTENSIDADE ESTILO MIXEA (DINÂMICA E VOLUME)
        int_level = intensidade.lower().strip()

        if int_level == "baixa":
            target_lufs = -12.5 if perfil in ["clear_sky", "aurora"] else -11.5
            comp_threshold_modifier = 1.0    
            ratio_multiplier = 0.8           
            limiter_ceiling = -1.0           
            
        elif int_level == "alta":
            target_lufs = -8.5 if perfil in ["clear_sky", "aurora"] else -7.0
            comp_threshold_modifier = -2.5   
            ratio_multiplier = 1.35          
            limiter_ceiling = -1.5           # Teto baixo protege contra distorção de interpolação [1.1.2]
            
        else: # "media"
            target_lufs = -10.5 if perfil in ["clear_sky", "aurora"] else -9.5
            comp_threshold_modifier = -0.5   
            ratio_multiplier = 1.0           
            limiter_ceiling = -1.2

        # 7. MATRIZ MID/SIDE
        L = audio_data[0, :]
        R = audio_data[1, :]
        mid = ((L + R) * 0.5).astype(np.float32)
        side = ((L - R) * 0.5).astype(np.float32)
        
        hp_mid = Pedalboard([HighpassFilter(cutoff_frequency_hz=30)])
        mid_filtered = hp_mid(mid[np.newaxis, :], sample_rate)[0]

        mid_low, mid_mid, mid_high = split_bands(mid_filtered, sample_rate)

        def get_band_rms_db(band_data):
            rms_val = np.sqrt(np.mean(band_data**2))
            return float(20 * np.log10(rms_val + 1e-9))

        rms_low_db = get_band_rms_db(mid_low)
        rms_mid_db = get_band_rms_db(mid_mid)
        rms_high_db = get_band_rms_db(mid_high)

        # 8. COMPRESSÃO MULTIBANDA ULTRA-GENTIL COM DE-ESSER AGRESSIVO NAS ALTAS
        final_ratio = max(1.0, soft_ratio * ratio_multiplier) 

        if perfil == "thunder":
            comp_low = Compressor(threshold_db=rms_low_db - 1.0 + comp_threshold_modifier, ratio=max(1.0, final_ratio * 1.1), attack_ms=45.0, release_ms=160.0)
            comp_mid = Compressor(threshold_db=rms_mid_db + comp_threshold_modifier, ratio=max(1.0, final_ratio), attack_ms=25.0, release_ms=150.0)
            # HIGH com ataque de 1ms age como De-esser cirúrgico para amparar fones brilhantes como o EDX PRO
            comp_high = Compressor(threshold_db=rms_high_db - 3.0 + comp_threshold_modifier, ratio=max(1.0, final_ratio * 1.3), attack_ms=1.0, release_ms=30.0)
            
        elif perfil == "clear_sky" or perfil == "clear sky":
            comp_low = Compressor(threshold_db=rms_low_db + comp_threshold_modifier, ratio=max(1.0, final_ratio * 0.9), attack_ms=50.0, release_ms=200.0)
            comp_mid = Compressor(threshold_db=rms_mid_db + comp_threshold_modifier, ratio=max(1.0, final_ratio * 0.8), attack_ms=30.0, release_ms=180.0)
            comp_high = Compressor(threshold_db=rms_high_db - 3.0 + comp_threshold_modifier, ratio=max(1.0, final_ratio * 1.2), attack_ms=1.0, release_ms=30.0)
            
        elif perfil == "sunroof":
            comp_low = Compressor(threshold_db=rms_low_db - 1.5 + comp_threshold_modifier, ratio=max(1.0, final_ratio * 1.2), attack_ms=25.0, release_ms=100.0)
            comp_mid = Compressor(threshold_db=rms_mid_db - 1.0 + comp_threshold_modifier, ratio=max(1.0, final_ratio * 1.1), attack_ms=15.0, release_ms=120.0)
            comp_high = Compressor(threshold_db=rms_high_db - 3.0 + comp_threshold_modifier, ratio=max(1.0, final_ratio * 1.4), attack_ms=1.0, release_ms=30.0)
            
        elif perfil == "aurora":
            comp_low = Compressor(threshold_db=rms_low_db + comp_threshold_modifier, ratio=max(1.0, final_ratio * 0.8), attack_ms=40.0, release_ms=250.0)
            comp_mid = Compressor(threshold_db=rms_mid_db + comp_threshold_modifier, ratio=max(1.0, final_ratio * 0.8), attack_ms=25.0, release_ms=220.0)
            comp_high = Compressor(threshold_db=rms_high_db - 3.0 + comp_threshold_modifier, ratio=max(1.0, final_ratio * 1.2), attack_ms=1.0, release_ms=30.0)

        mid_low_processed = comp_low(mid_low[np.newaxis, :], sample_rate)[0]
        mid_mid_processed = comp_mid(mid_mid[np.newaxis, :], sample_rate)[0]
        
        # 🟢 VACINA DE AGUDOS: Filtro passa-baixa em 15.5kHz descarta o "vidro" e aliasing inaudível da IA [1.1.8]
        # Adicionamos um atenuador dinâmico de sibilância dolorosa em 6.5kHz (pico de agressividade do EDX PRO) [1.2.2]
        clean_highs = Pedalboard([
            LowpassFilter(cutoff_frequency_hz=15500.0),
            PeakFilter(cutoff_frequency_hz=6500.0, gain_db=-2.0, q=1.5)
        ])
        mid_high_filtered = clean_highs(mid_high[np.newaxis, :], sample_rate)[0]
        mid_high_processed = comp_high(mid_high_filtered[np.newaxis, :], sample_rate)[0]

        # Recombinação
        mid_processed = mid_low_processed + mid_mid_processed + mid_high_processed

        # 9. EQUALIZAÇÃO CORRETIVA SUTIL (Apenas pinceladas tonais leves)
        bass_intensity = rms_low_db - rms_mid_db
        board_eq_mid = Pedalboard([])

        if perfil == "thunder":
            gain_low = max(0.0, 0.8 - (bass_intensity * 0.1)) if bass_intensity > 0 else 0.8
            board_eq_mid.append(LowShelfFilter(cutoff_frequency_hz=55.0, gain_db=gain_low))
        elif perfil == "clear_sky" or perfil == "clear sky":
            board_eq_mid.append(PeakFilter(cutoff_frequency_hz=3200.0, gain_db=0.4, q=0.5))
            # Removemos boosts excessivos de High Shelf para proteger contra sibilância
        elif perfil == "sunroof":
            board_eq_mid.append(LowShelfFilter(cutoff_frequency_hz=90.0, gain_db=0.4))
            board_eq_mid.append(HighShelfFilter(cutoff_frequency_hz=6000.0, gain_db=0.3))
        elif perfil == "aurora":
            board_eq_mid.append(LowShelfFilter(cutoff_frequency_hz=100.0, gain_db=0.4))
            board_eq_mid.append(Distortion(drive_db=0.5)) 

        mid_processed = board_eq_mid(mid_processed[np.newaxis, :], sample_rate)[0]

        # 10. PROCESSAMENTO ESPACIAL (SIDE) SEGURO
        # Limitamos o agudo das laterais em 14kHz para evitar que chiados de fase se espalhem [1.2.2]
        board_side = Pedalboard([
            HighpassFilter(cutoff_frequency_hz=150.0),
            LowpassFilter(cutoff_frequency_hz=14000.0)
        ])
        
        rms_side_db = get_band_rms_db(side)
        side_comp = Compressor(threshold_db=max(-40.0, rms_side_db - 4.0), ratio=max(1.0, final_ratio * 0.8), attack_ms=30.0, release_ms=150.0)
        board_side.append(side_comp)
        
        if perfil == "thunder":
            board_side.append(Gain(gain_db=0.4))
        elif perfil == "clear_sky" or perfil == "clear sky":
            board_side.append(Gain(gain_db=0.6))
        elif perfil == "sunroof":
            board_side.append(Gain(gain_db=0.8)) 
            board_side.append(PeakFilter(cutoff_frequency_hz=1500.0, gain_db=0.5, q=0.6))
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

        # Impede que o limitador final trabalhe duro em picos. Se a track exigir muito volume,
        # fazemos a compensação de forma pulverizada e nunca com pancada no limiter.
        if gain_needed > 5.0:
            pre_boost = gain_needed - 3.0
            audio_reconstructed = Pedalboard([Gain(gain_db=pre_boost)])(audio_reconstructed, sample_rate)
            gain_needed = 3.0

        oversampled_rate = sample_rate * 4.0
        board_master = Pedalboard([
            Resample(target_sample_rate=oversampled_rate),
            Gain(gain_db=gain_needed),
            Limiter(threshold_db=limiter_ceiling, release_ms=50.0), 
            Resample(target_sample_rate=sample_rate)
        ])

        final_audio = board_master(audio_reconstructed, sample_rate).T

        # 12. GRAVAÇÃO EM PCM_24
        sf.write(output_path, final_audio, sample_rate, format='WAV', subtype='PCM_24')
        
        tipo_processo = "PREVIEW" if is_preview else "MASTER"
        print(f"SUCESSO|{gain_needed + pre_gain_value:.2f}|{target_lufs:.1f}_LUFS|{tipo_processo}|{crest_factor_db:.2f}dB_Dinâmica|Teto_{limiter_ceiling:.1f}dBTP")

    except Exception as e:
        print(f"ERRO|{str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    if len(sys.argv) < 5:
        sys.exit(1)
        
    is_prev = True if len(sys.argv) == 6 and sys.argv[5] == 'true' else False
    masterize(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], is_prev)