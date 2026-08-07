import os
import logging
import json
import numpy as np
import soundfile as sf
from typing import Dict, Any, Optional
from dataclasses import dataclass, asdict

# Importação dos nossos blocos modulares validados em pytest [12]
from mastering_engine.analysis.metering import AudioMeter, AudioMetrics
from mastering_engine.dsp.crossover import LinkwitzRileyCrossover
from mastering_engine.dsp.stereo import MidSideStereoProcessor
from mastering_engine.dsp.transients import AdaptiveTransientShaper
from mastering_engine.dsp.limiter import TruePeakLimiter

logger = logging.getLogger("mastering_engine.pipeline.mastering")


@dataclass(frozen=True)
class MasteringProfile:
    """Configuração formal de diretrizes acústicas para perfis de estúdio [7]."""
    name: str
    target_lufs: float
    max_true_peak_dbtp: float
    stereo_width: float
    saturation_amount: float
    mono_bass_hz: float
    transient_intensity: float


# Dicionário de Perfis Oficiais de Masterização
OFFICIAL_PROFILES = {
    "clear_sky": MasteringProfile(
        name="clear_sky",
        target_lufs=-10.0,
        max_true_peak_dbtp=-1.0,
        stereo_width=1.1,
        saturation_amount=0.15,
        mono_bass_hz=120.0,
        transient_intensity=0.15
    ),
    "thunder": MasteringProfile(
        name="thunder",
        target_lufs=-9.0,
        max_true_peak_dbtp=-1.0,
        stereo_width=1.0,
        saturation_amount=0.30,  # Mais calor analógico
        mono_bass_hz=100.0,
        transient_intensity=0.20  # Peso rítmico extra
    ),
    "sunroof": MasteringProfile(
        name="sunroof",
        target_lufs=-11.0,
        max_true_peak_dbtp=-1.5,  # Headroom seguro para agudos abertos
        stereo_width=1.25,        # Campo estéreo estendido
        saturation_amount=0.10,
        mono_bass_hz=130.0,
        transient_intensity=0.10
    ),
    "aurora": MasteringProfile(
        name="aurora",
        target_lufs=-14.0,       # Padrão streaming dinâmico / acústico
        max_true_peak_dbtp=-2.0,
        stereo_width=1.05,
        saturation_amount=0.05,
        mono_bass_hz=140.0,
        transient_intensity=0.05
    )
}


class MasteringPipeline:
    """
    Orquestrador híbrido responsável por conduzir o fluxo sequencial de DSP
    e exportar relatórios de conformidade técnica Youlean-class [9].
    """
    
    def __init__(self, task_id: str, profile_name: str = "clear_sky"):
        self.task_id = task_id
        if profile_name not in OFFICIAL_PROFILES:
            logger.warning(f"Perfil '{profile_name}' desconhecido. Revertendo para 'clear_sky'.")
            profile_name = "clear_sky"
            
        self.profile = OFFICIAL_PROFILES[profile_name]
        logger.info(f"Pipeline inicializado para tarefa '{task_id}' utilizando perfil '{profile_name}'.")

    def masterize(
        self, 
        input_path: str, 
        output_path: str,
        is_preview: bool = False,
        custom_overrides: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Executa o pipeline completo de masterização híbrida.
        Retorna o relatório técnico em conformidade com as diretrizes SaaS [9].
        """
        if not os.path.exists(input_path):
            raise FileNotFoundError(f"Arquivo de entrada não encontrado: {input_path}")
            
        # 1. Carregar Áudio (Memory-safe com float32) [11]
        if is_preview:
            # Zero Latency Preview (ZLP): Lê apenas os 15 segundos centrais da música [5.1]
            info = sf.info(input_path)
            duration_samples = info.frames
            sample_rate = info.samplerate
            
            preview_len = int(15 * sample_rate)
            if duration_samples > preview_len:
                start_sample = (duration_samples - preview_len) // 2
                audio, sr = sf.read(input_path, start_time=start_sample, frames=preview_len, dtype="float32")
            else:
                audio, sr = sf.read(input_path, dtype="float32")
        else:
            audio, sr = sf.read(input_path, dtype="float32")
            
        # Garante representação estéreo (canais, amostras) [13]
        if len(audio.shape) == 1:
            audio_stereo = np.vstack((audio, audio))
        else:
            audio_stereo = audio.T
            
        # 2. Inicialização dos Motores de DSP baseados na Taxa de Amostragem detectada
        meter = AudioMeter(sample_rate=sr)
        
        # Carrega parâmetros mesclando baselines do perfil e overrides enviados pelo Angular (SaaS)
        overrides = custom_overrides or {}
        target_lufs = overrides.get("target_lufs", self.profile.target_lufs)
        ceiling_tp = overrides.get("ceiling_dbtp", self.profile.max_true_peak_dbtp)
        stereo_width = overrides.get("stereo_width", self.profile.stereo_width)
        sat_amount = overrides.get("saturation_amount", self.profile.saturation_amount)
        mono_bass = overrides.get("mono_bass_frequency_hz", self.profile.mono_bass_hz)
        transient_int = overrides.get("transient_intensity", self.profile.transient_intensity)
        
        # 3. Medição Inicial de Entrada (Youlean-Class)
        input_metrics = meter.analyze_signal(audio_stereo)
        
        # 4. Estágio Inicial de Ganho (Headroom de Segurança)
        # Normaliza temporariamente o pico discreto para -3 dBFS para evitar clipping interno nos filtros
        safety_headroom_linear = 10 ** (-3.0 / 20.0)
        current_peak_linear = np.max(np.abs(audio_stereo))
        
        if current_peak_linear > 1e-12:
            staged_audio = audio_stereo * (safety_headroom_linear / current_peak_linear)
        else:
            staged_audio = audio_stereo.copy()
            
        # 5. Processamento Estéreo Mid/Side (Mono Bass + Saturação Sem Aliasing + Salvaguarda)
        stereo_proc = MidSideStereoProcessor(sample_rate=sr, mono_bass_hz=mono_bass)
        processed_stereo = stereo_proc.process(
            staged_audio, 
            saturation_amount=sat_amount, 
            width_multiplier=stereo_width,
            correlation_safeguard=0.15
        )
        
        # 6. Modelador de Transientes Adaptativo Local (Protegido por Fator de Crista)
        transient_shaper = AdaptiveTransientShaper(sample_rate=sr)
        processed_transients = transient_shaper.process(
            processed_stereo, 
            intensity=transient_int, 
            global_crest_factor=input_metrics.crest_factor_db
        )
        
        # 7. Limitador Lookahead True Peak (Estágio de ganho final integrado)
        # O Threshold é calculado como o ganho necessário para atingir o LUFS alvo a partir do sinal normalizado
        # Mede o LUFS pós-processamento intermediário para calibração fina
        inter_metrics = meter.analyze_signal(processed_transients)
        required_gain_db = target_lufs - inter_metrics.integrated_lufs
        
        limiter = TruePeakLimiter(sample_rate=sr, ceiling_db=ceiling_tp, release_ms=100.0)
        final_master = limiter.process(processed_transients, threshold_db=required_gain_db)
        
        # 8. Medição Final de Saída
        output_metrics = meter.analyze_signal(final_master)
        
        # 9. Consolidação do Relatório JSON de Conformidade
        validation = {
            "loudness_pass": abs(output_metrics.integrated_lufs - target_lufs) <= 0.5,
            "true_peak_pass": output_metrics.true_peak_dbtp <= ceiling_tp + 0.1,
            "clipping_pass": output_metrics.sample_peak_dbfs <= 0.0,
            "mono_compatibility_pass": output_metrics.stereo_correlation >= 0.10
        }
        
        warnings = []
        if not validation["mono_compatibility_pass"]:
            warnings.append("Compatibilidade mono reduzida. Imagem estéreo muito aberta.")
        if output_metrics.true_peak_dbtp > 0.0:
            warnings.append("Perigo de distorção interamostra pós-conversão.")
            
        report = {
            "task_id": self.task_id,
            "status": "completed",
            "is_preview": is_preview,
            "decisions": {
                "profile": self.profile.name,
                "target_lufs": target_lufs,
                "max_true_peak_dbtp": ceiling_tp,
                "applied_mid_side_sat": sat_amount,
                "applied_stereo_width": stereo_width,
                "applied_transient_boost": transient_int,
                "applied_limiter_gain_db": round(required_gain_db, 2)
            },
            "input": input_metrics.model_dump(),
            "output": output_metrics.model_dump(),
            "validation": validation,
            "warnings": warnings
        }
        
        # 10. Exportação do Arquivo de Áudio Final (WAV PCM 24 bits de alta definição)
        # Converte de volta para samples primeiro (amostras, canais) antes de salvar no disco
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        sf.write(output_path, final_master.T, sr, subtype="PCM_24")
        logger.info(f"Masterização concluída. Arquivo exportado para: {output_path}")
        
        return report