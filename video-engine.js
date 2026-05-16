const path = require('path');
const ffmpeg = require('fluent-ffmpeg');

const audioInput = path.join(__dirname, 'dist', 'THE_BLUEPRINT_SESSIONS_VOL_004.mp3');
const imageInput = path.join(__dirname, 'bg-video.jpg');
const videoOutput = path.join(__dirname, 'dist', 'TESTE_VISUAL_15_SEGUNDOS.mp4');

// Coordenadas do Holograma
const tvWidth = 400;
const tvHeight = 200;
const tvX = 560;
const tvY = 390;

console.log('💻 RQS_DAW: A iniciar DEPLOY ABSOLUTO (Monólito de 32 Minutos)...');

ffmpeg()
    .input(imageInput)
    .inputOptions(['-loop 1'])
    .input(audioInput)
    .complexFilter([
        // 1. NORMALIZAÇÃO DA ARTE
        `[0:v]scale=trunc(iw/2)*2:trunc(ih/2)*2,format=rgb24[bg]`,

        // 2. OVERDRIVE DE ESPECTRO (Volume 5x visual)
        `[1:a]volume=5.0,showfreqs=mode=bar:fscale=log:s=${tvWidth}x${tvHeight}:colors=cyan|cyan:ascale=log,format=rgba,colorkey=black:0.1:0.2[waves]`,

        // 3. OVERLAY (Fusão da arte com as ondas)
        `[bg][waves]overlay=x=${tvX}:y=${tvY}:shortest=1[out]`
    ])
    .outputOptions([
        '-map [out]',
        '-map 1:a',
        // 🚫 TRAVA DE 15 SEGUNDOS REMOVIDA. RENDERIZAÇÃO LIVRE.
        '-c:v libx264',
        '-pix_fmt yuv420p',
        '-preset fast', // Qualidade otimizada para YouTube
        '-c:a copy'     // Proteção absoluta do áudio
    ])
    .on('start', () => console.log('⚙️ Compilação iniciada. Acionando dissipadores do chassi. A Forja está a queimar...'))
    .on('progress', (progress) => {
        // Telemetria em tempo real no terminal
        if (progress.timemark) {
            process.stdout.write(`\r[Renderização]: Compilando linha do tempo: ${progress.timemark} ...`);
        }
    })
    .on('end', () => console.log('\n\n💎 Deploy Absoluto Concluído! O arquivo THE_BLUEPRINT_SESSIONS_VOL_004_FINAL.mp4 está pronto para o mundo.'))
    .on('error', (err, stdout, stderr) => {
        console.error('\n\n🛡️ Falha Catastrófica no Kernel:', err.message);
        console.error('\n📋 LOG CAIXA PRETA:\n', stderr);
    })
    .save(videoOutput);