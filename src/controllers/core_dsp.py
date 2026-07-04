import sys
import gc
import numpy as np
import soundfile as sf
import pyloudnorm as pyln
from scipy.signal import butter, sosfiltfilt, stft, istft
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

def restore_transients(signal: np.ndarray, crest_factor: float, sample_rate: float):
    """
    MÓDULO TRANSIENTE: Computa a derivada da amplitude para detectar ataques rápidos (transientes)
    e aplica um ganho adaptativo pré-compressão para devolver o punch de baterias esmagadas.
    """
    if crest_factor >= 8.5:
        return signal  # Preserva se a música já tiver dinâmica saudável
        
    abs_signal = np.abs(signal)
    
    # Envelope rápido via filtro de convolução digital de 5ms
    window_size = int(0.005 * sample_rate)
    if window_size < 1:
        window_size = 1
    window = np.exp(-np.arange(window_size) / (window_size / 2.0))
    window /= np.sum(window)
    
    envelope = np.convolve(abs_signal, window, mode='same')
    
    # Derivada do envelope para capturar taxas de subida rápidas (ataques)
    derivative = np.diff(envelope, prepend=0)
    derivative = np.maximum(0, derivative)  # Foca apenas no ganho dos ataques positivos
    
    max_deriv = np.max(derivative) + 1e-9
    normalized_transients = derivative / max_deriv
    
    # Aplica um ganho adaptativo de até +1.5dB (fator de 1.18) no início dos transientes
    boost_factor = 1.0 + 0.18 * normalized_transients
    return (signal * boost_factor).astype(np.float32)

def tame_resonances(signal: np.ndarray, sample_rate: float, low_freq: float = 2500.0, high_freq: float = 5000.0):
    """
    RESTAURAÇÃO IA: Implementa análise FFT em janelas de tempo curtas (STFT) para identificar
    picos de ressonância isolados na região de harshness (2.5kHz-5kHz) e aplicar atenuação cirúrgica.
    """
    nperseg = 2048
    noverlap = 1536  # Overlap de 75% para suavidade na reconstrução de fase
    
    frequencies, times, Zxx = stft(signal, fs=sample_rate, nperseg=nperseg, noverlap=noverlap)
    
    # Máscara para a faixa de harshness (2.5kHz a 5.0kHz)
    freq_mask = (frequencies >= low_freq) & (frequencies <= high_freq)
    
    # Piso de ruído médio em cada frame de tempo
    avg_magnitude = np.mean(np.abs(Zxx), axis=0, keepdims=True)
    
    # Identifica bins isolados que ultrapassam o limiar médio do frame em 4.0 vezes (+12dB)
    threshold_ratio = 4.0
    attenuation_factor = 0.5  # Atenuação cirúrgica de -6dB
    
    Zxx_modified = Zxx.copy()
    magnitudes = np.abs(Zxx)
    is_peak = (magnitudes > avg_magnitude * threshold_ratio) & freq_mask[:, np.newaxis]
    
    # Aplica a atenuação dinâmica
    Zxx_modified[is_peak] *= attenuation_factor
    
    # Reconstrói o sinal de áudio limpo por STFT Inversa (ISTFT)
    _, signal_tamed = istft(Zxx_modified, fs=sample_rate, nperseg=nperseg, noverlap=noverlap)
    
    # Tratamento de segurança contra incompatibilidades de tamanho de array
    if len(signal_tamed) > len(signal):
        signal_tamed = signal_tamed[:len(signal)]
    elif len(signal_tamed) < len(signal):
        signal_tamed = np.pad(signal_tamed, (0, len(signal) - len(signal_tamed)))
        
    return signal_tamed.astype(np.float32)

def saturate_side(side_channel: np.ndarray, sample_rate: float):
    """
    SATURAÇÃO HARMÔNICA: Aplica funções de transferência não-lineares (tanh) sutilmente 
    apenas nas altas frequências do canal Side para gerar brilho estéreo de fita analógica.
    """
    # Isola o topo de frequências estéreo acima de 5kHz
    sos_hp = butter(2, 5000.0, btype='high', fs=sample_rate, output='sos')
    side_highs = sosfiltfilt(sos_hp, side_channel)
    
    # Função de saturação suave não-linear (tangente hiperbólica)
    drive = 1.15
    saturated_highs = np.tanh(side_highs * drive) / drive
    
    # Devolve as frequências saturadas de volta ao canal Side
    return (side_channel - side_highs + saturated_highs).astype(np.float32)

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
            limiter_ceiling = -1.5           
            
        else: # "media"
            target_lufs = -10.5 if perfil in ["clear_sky", "aurora"] else -9.5
            comp_threshold_modifier = -0.5   
            ratio_multiplier = 1.0           
            limiter_ceiling = -1.2

        # 7. MATRIZ MID/SIDE E PROCESSADORES DE SINAL INTEGRAIS
        L = audio_data[0, :]
        R = audio_data[1, :]
        mid = ((L + R) * 0.5).astype(np.float32)
        side = ((L - R) * 0.5).astype(np.float32)
        
        # MÓDULO 1: Restauração dinâmica de transientes no canal central [1.2]
        mid = restore_transients(mid, crest_factor_db, sample_rate)
        
        # MÓDULO 2: Limpeza de ressonâncias dinâmicas e sibilâncias via STFT [1.1.2]
        mid = tame_resonances(mid, sample_rate)
        
        # MÓDULO 3: Saturação harmônica não-linear no canal lateral estéreo [1.2]
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

        # 8. COMPRESSÃO MULTIBANDA ULTRA-GENTIL COM DE-ESSER AGRESSIVO NAS ALTAS
        final_ratio = max(1.0, soft_ratio * ratio_multiplier) 

        if perfil == "thunder":
            comp_low = Compressor(threshold_db=rms_low_db - 1.0 + comp_threshold_modifier, ratio=max(1.0, final_ratio * 1.1), attack_ms=45.0, release_ms=160.0)
            comp_mid = Compressor(threshold_db=rms_mid_db + comp_threshold_modifier, ratio=max(1.0, final_ratio), attack_ms=25.0, release_ms=150.0)
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
        
        # Filtro de corte cirúrgico contra o aliasing digital inaudível da IA acima de 15.5kHz [1.1.8]
        # Adiciona atenuador cirúrgico contra a sibilância na frequência de pico de fones como o EDX PRO [1.2.2]
        clean_highs = Pedalboard([
            LowpassFilter(cutoff_frequency_hz=15500.0),
            PeakFilter(cutoff_frequency_hz=6500.0, gain_db=-2.0, q=1.5)
        ])
        mid_high_filtered = clean_highs(mid_high[np.newaxis, :], sample_rate)[0]
        mid_high_processed = comp_high(mid_high_filtered[np.newaxis, :], sample_rate)[0]

        # Recombinação
        mid_processed = mid_low_processed + mid_mid_processed + mid_high_processed

        # 9. EQUALIZAÇÃO CORRETIVA SUTIL (Mudanças de milímetros)
        bass_intensity = rms_low_db - rms_mid_db # 🟢 CORREÇÃO: Variável reinserida com sucesso! [1.2]
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

        # 10. PROCESSAMENTO ESPACIAL (SIDE) SEGURO
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

        # Impede que o limitador final trabalhe duro em picos
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