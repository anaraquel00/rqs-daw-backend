const express = require('express');
const router = express.Router();
const multer = require('multer');
const path = require('path');
const fs = require('fs');
const ffmpeg = require('fluent-ffmpeg');

// 🛡️ O Interceptador de Carga: Aceita até 20 faixas simultâneas no campo 'tracks'
const upload = multer({ dest: 'uploads/' });

router.post('/generate', upload.array('tracks', 20), (req, res) => {
    try {
        console.log('💻 [MIX ENGINE] Iniciando cruzamento de faixas da Setlist via API...');

        const uploadedFiles = req.files; // Array de arquivos que o Angular vai enviar
        
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
            return res.status(400).json({ error: 'A Vinheta de ID Drop não foi encontrada no servidor.' });
        }

        console.log(`📋 ORDEM DE COMPILAÇÃO: ${uploadedFiles.length} faixas injetadas na linha do tempo.`);

        let command = ffmpeg();

        // 1. INJETA A VINHETA NO CANAL 0 (Prioridade Máxima)
        command.input(vignettePath);

        // 2. INJETA AS MÚSICAS TEMPORÁRIAS NOS CANAIS 1 até N
        // Detalhe sênior: a ordem do array aqui é exatamente a ordem que a General organizar lá no Angular!
        uploadedFiles.forEach(file => command.input(file.path));

        let complexFilter = [];
        let lastOutput = '1:a'; 

        // 3. COSTURA AS MÚSICAS (Crossfade de 0.5s)
        if (uploadedFiles.length > 1) {
            for (let i = 2; i <= uploadedFiles.length; i++) {
                let nextInput = `${i}:a`;
                let currentOutput = `xfade${i}`;

                complexFilter.push({
                    filter: 'acrossfade',
                    options: { d: 0.5 },
                    inputs: [lastOutput, nextInput],
                    outputs: currentOutput
                });

                lastOutput = currentOutput;
            }
        }

        // 4. PROTOCOLO DE SOBREPOSIÇÃO DA ORDEM
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

        // Execução do FFmpeg
        command
            .on('start', () => console.log('⚙️ Compilando Setlist com Assinatura RQS...'))
            .on('end', () => {
                console.log('💎 Deploy da Setlist Concluído! Transmitindo a Master para o Front-End.');
                
                res.download(outputFile, outputFileName, (err) => {
                    // Limpeza do HD após o download
                    if (!err && fs.existsSync(outputFile)) fs.unlinkSync(outputFile);
                    
                    // 🧹 PROTOCOLO DE LIXEIRO (Gargage Collection Manual)
                    // Deleta todas as músicas temporárias que o Front-End enviou para não entupir o servidor
                    uploadedFiles.forEach(f => {
                        if (fs.existsSync(f.path)) fs.unlinkSync(f.path);
                    });
                });
            })
            .on('error', (err) => {
                console.error('\n🛡️ Falha Crítica no Pipeline FFmpeg:', err.message);
                if (!res.headersSent) res.status(500).json({ error: 'Falha na renderização da Setlist.' });
            })
            .save(outputFile);

    } catch (error) {
        console.error('[CRITICAL] O Roteador de Mixagem sofreu um colapso:', error);
        res.status(500).json({ error: 'Erro interno no motor do Mainframe' });
    }
});

module.exports = router;