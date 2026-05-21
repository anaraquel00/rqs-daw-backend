const express = require('express');
const router = express.Router();
const path = require('path');
const fs = require('fs');
const ffmpeg = require('fluent-ffmpeg');

router.post('/render', (req, res) => {
    try {
        // Lemos a facção enviada pelo Front-End (por padrão, a Ordem impera)
        const preset = req.body.preset || 'blue_team'; 

        let bgImage, waveColors, outputExt, ffmpegFlags, tvX, tvY;

        // 🎛️ O ROTEADOR DE FACÇÕES
        if (preset === 'red_team' || preset === 'jonah') {
            console.log('💀 [RED_TEAM_DAW]: A iniciar DEPLOY DA CARNIFICINA...');
            bgImage = 'bloodprint_bg.jpg';
            waveColors = 'red|DarkRed'; // O sangue do Jonah
            outputExt = 'mkv'; // Contêiner sujo e resistente a corrupção
            ffmpegFlags = ['-preset veryfast', '-crf 18']; 
            tvX = 690; tvY = 370; // Coordenadas do CRT quebrado
        } else {
            console.log('🛡️ [BLUE_TEAM_DAW]: Inicializando Renderização da Ordem. Frequências cristalinas...');
            bgImage = 'synthwave_bg.jpg'; // O background limpo e neon da Kelma
            waveColors = 'cyan|blue'; // A assinatura da RQS
            outputExt = 'mp4'; // Padrão ouro da indústria, polido e comprimido
            ffmpegFlags = ['-preset medium', '-crf 20']; // Mais tempo de CPU para garantir a nitidez perfeita
            tvX = 400; tvY = 400; // Coordenadas centralizadas de um monitor holográfico perfeito (Ajuste conforme sua arte)
        }

        // Lógica de I/O
        const audioInput = req.body.audioUrl 
            ? path.join(__dirname, '../../', req.body.audioUrl) 
            : path.join(__dirname, '../../dist', 'THE_BLOODPRINT_SESSIONS_VOL_002.wav');
            
        const imageInput = path.join(__dirname, '../../assets', bgImage);
        const outputFileName = `RQS_VISUAL_${preset.toUpperCase()}_${Date.now()}.${outputExt}`;
        const videoOutput = path.join(__dirname, '../../dist', outputFileName);

        if (!fs.existsSync(audioInput) || !fs.existsSync(imageInput)) {
            return res.status(400).json({ error: `🚫 [BLOCK]: Artefatos visuais (${bgImage}) ou áudio ausentes na base.` });
        }

        const tvWidth = 400;
        const tvHeight = 200;

        ffmpeg()
            .input(imageInput)
            .inputOptions(['-loop 1'])
            .input(audioInput)
            .complexFilter([
                // 1. NORMALIZAÇÃO DA ARTE (Respeitando a resolução base)
                `[0:v]scale=trunc(iw/2)*2:trunc(ih/2)*2,format=rgb24[bg]`,

                // 2. ESPECTRO DE ENERGIA (As cores mudam conforme a facção!)
                `[1:a]volume=5.0,showfreqs=mode=bar:fscale=log:s=${tvWidth}x${tvHeight}:colors=${waveColors}:ascale=log,format=rgba,colorkey=black:0.1:0.2[waves]`,

                // 3. OVERLAY (Ondas injetadas na matriz visual)
                `[bg][waves]overlay=x=${tvX}:y=${tvY}:shortest=1[out]`
            ])
            .outputOptions([
                '-map [out]',
                '-map 1:a',
                '-t 15', // Remova essa linha depois para renderizar a música inteira
                '-c:v libx264',
                '-pix_fmt yuv420p',
                ...ffmpegFlags, // Desempacota as flags de renderização baseadas na facção
                '-c:a copy'
            ])
            .on('end', () => {
                console.log(`💎 Deploy Visual Concluído! Transmitindo [${outputFileName}] para a General.`);
                res.download(videoOutput, outputFileName, (err) => {
                    if (!err && fs.existsSync(videoOutput)) fs.unlinkSync(videoOutput);
                });
            })
            .on('error', (err) => {
                console.error('\n💥 Falha de Renderização no Motor Híbrido:', err.message);
                if (!res.headersSent) res.status(500).json({ error: 'Colapso na engine de vídeo.' });
            })
            .save(videoOutput);

    } catch (error) {
        console.error('[CRITICAL] Erro no roteamento visual:', error);
        res.status(500).json({ error: 'A Matrix rejeitou a compilação.' });
    }
});

module.exports = router;