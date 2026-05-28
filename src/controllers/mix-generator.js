const express = require('express');
const router = express.Router();
const multer = require('multer');
const path = require('path');
const fs = require('fs');
const ffmpeg = require('fluent-ffmpeg');

// 🛡️ O Interceptador de Carga
const upload = multer({ dest: 'uploads/' });

router.post('/generate', upload.array('tracks', 20), (req, res) => {
    try {
        console.log('💻 [MIX ENGINE] Iniciando cruzamento ponto-a-ponto via API...');

        const uploadedFiles = req.files; 
        
        // 🎛️ CAPTURA MICRO-CIRÚRGICA DOS CROSSFADES
        let fadeDurations = [];
        try {
            if (req.body.crossfades) {
                fadeDurations = JSON.parse(req.body.crossfades);
            }
        } catch (error) {
            console.error('⚠️ Erro ao interpretar os crossfades customizados. Usando Fail-Safe.', error);
        }
        
        console.log(`[MIX ENGINE] Matriz de Crossfades interceptada: [${fadeDurations.join(', ')}]`);

        // Validação de Barramento
        if (!uploadedFiles || uploadedFiles.length === 0) {
            return res.status(400).json({ error: 'Nenhuma faixa foi detectada no barramento de entrada.' });
        }

        const vignettePath = path.join(__dirname, '../../assets', 'VIGNETTE_MAIN.wav'); 
        const outputFileName = `RQS_SETLIST_${Date.now()}.wav`;
        const outputDir = path.join(__dirname, '../../dist');
        const outputFile = path.join(outputDir, outputFileName);

        if (!fs.existsSync(outputDir)) fs.mkdirSync(outputDir, { recursive: true });
        if (!fs.existsSync(vignettePath)) {
            console.error('[CRITICAL] VIGNETTE não encontrada.');
            return res.status(400).json({ error: 'A Vinheta de ID Drop não foi encontrada.' });
        }

        let command = ffmpeg();

        // 1. Vinheta no Canal 0
        command.input(vignettePath);

        // 2. Músicas nos Canais de 1 até N
        uploadedFiles.forEach(file => command.input(file.path));

        let complexFilter = [];
        let lastOutput = '1:a'; 

        // 3. COSTURA BISTURI (Crossfade Ponto-a-Ponto)
        if (uploadedFiles.length > 1) {
            for (let i = 2; i <= uploadedFiles.length; i++) {
                let nextInput = `${i}:a`;
                let currentOutput = `xfade${i}`;

                // 🛡️ O MOTOR MATEMÁTICO: Puxa o índice exato do Array. (i - 2 porque o loop começa em 2)
                let currentFadeRaw = fadeDurations[i - 2];
                // Fail-safe: Se o valor for inválido ou não existir, injeta 8.0
                let currentFade = (currentFadeRaw !== undefined && currentFadeRaw !== null) ? parseFloat(currentFadeRaw) : 8.0;

                console.log(`⚙️ Injetando transição de ${currentFade}s entre Faixa ${i-1} e Faixa ${i}`);

                complexFilter.push({
                    filter: 'acrossfade',
                    options: { d: currentFade }, // 💎 O valor correto, seguro e numérico!
                    inputs: [lastOutput, nextInput],
                    outputs: currentOutput
                });

                lastOutput = currentOutput;
            }
        }

        // 4. PROTOCOLO DE SOBREPOSIÇÃO
        complexFilter.push({
            filter: 'adelay',
            options: '2000|2000',
            inputs: '0:a',
            outputs: 'vignette_delayed'
        });

        complexFilter.push({
            filter: 'volume',
            options: '0.8',
            inputs: lastOutput,
            outputs: 'music_ducked'
        });

        complexFilter.push({
            filter: 'amix',
            options: { inputs: 2, duration: 'longest', normalize: 0 },
            inputs: ['vignette_delayed', 'music_ducked'],
            outputs: 'final_master'
        });

        command.complexFilter(complexFilter, 'final_master');

        command
            .on('start', () => console.log('⚙️ Compilando Setlist com precisão cirúrgica...'))
            .on('end', () => {
                console.log('💎 Deploy Concluído! Transmitindo...');
                res.download(outputFile, outputFileName, (err) => {
                    if (!err && fs.existsSync(outputFile)) fs.unlinkSync(outputFile);
                    uploadedFiles.forEach(f => {
                        if (fs.existsSync(f.path)) fs.unlinkSync(f.path);
                    });
                });
            })
            .on('error', (err) => {
                console.error('\n🛡️ Falha Crítica no Pipeline:', err.message);
                if (!res.headersSent) res.status(500).json({ error: 'Falha na renderização da Setlist.' });
            })
            .save(outputFile);

    } catch (error) {
        console.error('[CRITICAL] Colapso geral:', error);
        res.status(500).json({ error: 'Erro interno no motor.' });
    }
});

module.exports = router;