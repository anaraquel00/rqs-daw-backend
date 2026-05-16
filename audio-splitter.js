const path = require('path');
const ffmpeg = require('fluent-ffmpeg');

const inputMaster = path.join(__dirname, 'dist', 'THE_BLUEPRINT_SESSIONS_VOL_004.mp3');
const outputPattern = path.join(__dirname, 'dist', 'CHUNK_VOL_004_%03d.mp3');

console.log('💻 RQS_DAW: A iniciar Protocolo de Fatiamento (Chunking)...');

ffmpeg(inputMaster)
    .outputOptions([
        '-f segment',
        '-segment_time 600', // Corta exatamente a cada 10 minutos (600 segundos)
        '-c copy'            // Cópia direta do kernel sem re-encodar (instantâneo)
    ])
    .on('start', () => console.log('⚙️ A fatiar o Monólito em micro-serviços de 10 minutos...'))
    .on('end', () => console.log('\n💎 Fatiamento concluído! Verifique a pasta /dist.'))
    .on('error', (err) => console.error('\n🛡️ Erro no Kernel:', err.message))
    .save(outputPattern);