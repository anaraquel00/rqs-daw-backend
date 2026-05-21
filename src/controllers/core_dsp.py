import sys
import gc
import numpy as np
import soundfile as sf
import pyloudnorm as pyln
from scipy.signal import butter, sosfiltfilt
from pedalboard import Pedalboard, Compressor, HighpassFilter, HighShelfFilter, LowShelfFilter, Limiter, Gain, Resample

def split_bands(signal: np.ndarray, sample_rate: float, low_cutoff: float = 120.0, high_cutoff: float = 5000.0):
    """
    Divide o canal mono de áudio em 3 bandas físicas usando filtros Butterworth de 2a ordem
    processados bidirecionalmente (sosfiltfilt) para garantir distorção de fase linear zero
    e somatório perfeitamente plano (Linkwitz-Riley equivalente de 4a ordem).
    """
    # Filtro Low-Pass estável para o subgrave
    sos_low = butter(2, low_cutoff, btype='low', fs=sample_rate, output='sos')
    low_band = sosfiltfilt(sos_low, signal)
    
    # Filtro High-Pass estável para o brilho e artefatos de IA
    sos_high = butter(2, high_cutoff, btype='high', fs=sample_rate, output='sos')
    high_band = sosfiltfilt(sos_high, signal)
    
    # Crossover subtrativo para garantir reconstrução plana idêntica e sem cancelamento
    mid_band = signal - low_band - high_band
    
    return low_band.astype(np.float32), mid_band.astype(np.float32), high_band.astype(np.float32)

def masterize(input_path: str, output_path: str, estilo: str, intensidade: str, is_preview: bool = False):
    try:
        # 1. LEITURA BLINDADA E OTIMIZADA DE ÁUDIO
        # Força float32 diretamente no parser do arquivo para reduzir o consumo de memória imediatamente
        audio_data, sample_rate = sf.read(input_path, dtype='float32')
        
        # Blindagem Mono-to-Stereo robusta para arrays 1D ou 2D com única coluna
        if audio_data.ndim == 1:
            audio_data = np.column_stack((audio_data, audio_data))
        elif audio_data.ndim == 2 and audio_data.shape[1] == 1:
            mono_flat = audio_data.squeeze()
            audio_data = np.column_stack((mono_flat, mono_flat))
            
        # Certifica que os dados estão estritamente no layout (canais, amostras) para processamento eficiente
        audio_data = audio_data.T

        # 2. MOTOR DE PREVIEW (Corte Temporal Inteligente)
        if is_preview:
            total_samples = audio_data.shape[1]
            total_duration_sec = total_samples / sample_rate
            
            # Pegamos 15 segundos do centro exato da música (maior probabilidade de pico dinâmico/refrão)
            if total_duration_sec > 15.0:
                start_sec = (total_duration_sec / 2.0) - 7.5
                end_sec = start_sec + 15.0
                audio_data = audio_data[:, int(start_sec * sample_rate):int(end_sec * sample_rate)]

        # 3. ANÁLISE ADAPTATIVA DSP (Redução da Dinâmica Geral)
        meter = pyln.Meter(sample_rate)
        # O Pyloudnorm exige layout (amostras, canais)
        input_lufs = meter.integrated_loudness(audio_data.T)
        
        rms = np.sqrt(np.mean(audio_data**2))
        peak = np.max(np.abs(audio_data))
        crest_factor_db = float(20 * np.log10(peak / (rms + 1e-9)))

        # Ajuste adaptativo inteligente da taxa de compressão
        dynamic_ratio = float(1.5 if crest_factor_db < 10.0 else 2.5)
        dynamic_threshold = float(input_lufs + 3.0)

        # 4. MATRIZ MID/SIDE ADAPTATIVA
        L = audio_data[0, :]
        R = audio_data[1, :]
        
        # Geração dos sinais Mid e Side com peso distribuído uniformemente
        mid = ((L + R) * 0.5).astype(np.float32)
        side = ((L - R) * 0.5).astype(np.float32)
        
        # Filtro subsônico rigoroso no canal MID para expurgar 'Rumble' e DC offsets indesejados da Suno AI
        hp_mid = Pedalboard([HighpassFilter(cutoff_frequency_hz=30)])
        mid_filtered = hp_mid(mid[np.newaxis, :], sample_rate)[0]

        # Divisão multibanda no canal MID filtrado
        mid_low, mid_mid, mid_high = split_bands(mid_filtered, sample_rate)

        # Configurações dinâmicas para as 3 bandas físicas do MID
        # LOW: Compressão firme para reter a energia do subgrave sem pulsações irritantes
        comp_low = Compressor(threshold_db=dynamic_threshold - 3.0, ratio=dynamic_ratio * 1.5, attack_ms=30.0, release_ms=200.0)
        mid_low_processed = comp_low(mid_low[np.newaxis, :], sample_rate)[0]

        # MID: Foco na naturalidade de instrumentos e vocais
        comp_mid = Compressor(threshold_db=dynamic_threshold, ratio=dynamic_ratio, attack_ms=15.0, release_ms=150.0)
        mid_mid_processed = comp_mid(mid_mid[np.newaxis, :], sample_rate)[0]

        # HIGH: De-esser e controle de agudos estridentes gerados por geradores neurais
        comp_high = Compressor(threshold_db=dynamic_threshold - 1.5, ratio=max(1.1, dynamic_ratio * 0.8), attack_ms=3.0, release_ms=50.0)
        mid_high_processed = comp_high(mid_high[np.newaxis, :], sample_rate)[0]

        # Recombinação perfeita de banda
        mid_processed = mid_low_processed + mid_mid_processed + mid_high_processed

        # Estilo de Modelagem Analógica / EQ
        if estilo == "aberto":
            shelf_mid = Pedalboard([LowShelfFilter(cutoff_frequency_hz=60.0, gain_db=1.0)])
            mid_processed = shelf_mid(mid_processed[np.newaxis, :], sample_rate)[0]
        elif estilo == "quente":
            shelf_mid = Pedalboard([LowShelfFilter(cutoff_frequency_hz=100.0, gain_db=2.0)])
            mid_processed = shelf_mid(mid_processed[np.newaxis, :], sample_rate)[0]

        # Processamento do canal espacial SIDE (Filtro passa-altas rigoroso previne cancelamento mono no subgrave)
        board_side = Pedalboard([HighpassFilter(cutoff_frequency_hz=150.0)])
        if estilo == "aberto":
            board_side.append(HighShelfFilter(cutoff_frequency_hz=6000.0, gain_db=1.5))
        elif estilo == "quente":
            board_side.append(HighShelfFilter(cutoff_frequency_hz=4000.0, gain_db=1.0))

        # Otimização DSP: Se o sinal Side for nulo (faixa mono pura), pulamos o processamento estéreo para economizar CPU
        if np.any(side):
            side_processed = board_side(side[np.newaxis, :], sample_rate)[0]
        else:
            side_processed = np.zeros_like(mid_processed)

        # Reconstrução da matriz estéreo original com as alterações processadas
        L_new = mid_processed + side_processed
        R_new = mid_processed - side_processed
        audio_reconstructed = np.vstack((L_new, R_new))

        # Liberação preventiva de arrays temporários pesados da memória RAM antes de passar para o estágio final do limitador
        del L, R, mid, side, mid_filtered, mid_low, mid_mid, mid_high, mid_low_processed, mid_mid_processed, mid_high_processed, L_new, R_new
        gc.collect()

        # 5. CÁLCULO DE GANHO E SELEÇÃO DE INTENSIDADE (EBU R128)
        target_lufs = -14.0 if intensidade == "media" else (-16.0 if intensidade == "baixa" else -9.0)
        
        audio_for_meter = audio_reconstructed.T
        current_lufs = meter.integrated_loudness(audio_for_meter)
        gain_needed = target_lufs - current_lufs

        # 6. LIMITADOR TRUE PEAK ABSOLUTO COM OVERSAMPLING 4X (APPLE DIGITAL MASTERS STYLE)
        # O upsampling pré-clipping expõe as micro variações analógicas que passariam pelo limitador comum
        oversampled_rate = sample_rate * 4.0
        
        board_master = Pedalboard([
            Resample(target_sample_rate=oversampled_rate),  # Upsample 4x
            Gain(gain_db=gain_needed),
            Limiter(threshold_db=-1.1, release_ms=50.0),    # Teto de -1.1 dB protege contra a modulação do filtro de descida
            Resample(target_sample_rate=sample_rate)        # Downsample de volta à taxa de amostragem original
        ])

        final_audio = board_master(audio_reconstructed, sample_rate).T

        # 7. EXPORTAÇÃO DE EXTREMA PRECISÃO EM 24 BITS (PCM_24)
        # O padrão PCM_24 garante que não haja ruído de truncamento digital nas caixas acústicas
        sf.write(output_path, final_audio, sample_rate, format='WAV', subtype='PCM_24')
        
        tipo_processo = "PREVIEW" if is_preview else "MASTER"
        print(f"SUCESSO|{gain_needed:.2f}|{target_lufs}|{tipo_processo}|{crest_factor_db:.2f}dB_Dinâmica")

    except Exception as e:
        print(f"ERRO|{str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    if len(sys.argv) < 5:
        sys.exit(1)
        
    is_prev = True if len(sys.argv) == 6 and sys.argv[5] == 'true' else False
    masterize(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], is_prev)