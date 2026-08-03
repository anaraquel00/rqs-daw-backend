const express = require('express');
const router = express.Router();
const multer = require('multer');
const path = require('path');
const fs = require('fs');
const ffmpeg = require('fluent-ffmpeg');

// 🟢 MÓDULO S3: SDKs oficiais da AWS para o fluxo de alta performance [1.3.0]
const { S3Client, GetObjectCommand, PutObjectCommand } = require("@aws-sdk/client-s3");
const { getSignedUrl } = require("@aws-sdk/s3-request-presigner");

// 🟢 Inicializa o S3Client apontando para São Paulo [1.3.0]
const s3Client = new S3Client({ region: "sa-east-1" });
const BUCKET_NAME = "amzn-rqs-bunker-sa";

// 🛡️ O Interceptador de Carga
const upload = multer({ dest: '/tmp/' });

// ======================================================================================
// 🟢 ROTA S3 NOVA: POST /mix/generate-s3 (Fluxo de Alta Performance com Bunker) [1.3.0]
// ======================================================================================
router.post('/generate-s3', async (req, res) => {
    // 🛡️ PROTOCOLO SRE: Log detalhado do payload de entrada para rastreabilidade [1.3.1]
    console.log('[MIX ENGINE S3] Payload recebido:', JSON.stringify(req.body, null, 2));
    const { s3Keys, crossfades, curva, loudness, exportName } = req.body;

    // 🛡️ PROTOCOLO SRE: Validação de Schema do Payload [1.3.1]
    if (!s3Keys || !Array.isArray(s3Keys) || s3Keys.length === 0) {
        console.error('[CRITICAL S3] Falha de validação do payload: s3Keys está ausente, não é um array ou está vazio.');
        return res.status(400).json({ error: 'Payload inválido: A propriedade "s3Keys" é obrigatória e deve ser uma lista de chaves S3.' });
    }

    const localFilePaths = [];
    const outputFileName = `${(exportName || 'RQS_SETLIST').replace(/ /g, '_')}_${Date.now()}.wav`;
    const outputFile = path.join('/tmp/', outputFileName);

    // Função de Limpeza de Emergência (Higienização de Disco)
    const cleanup = (filesToClean, outputPath) => {
        filesToClean.forEach(filePath => {
            if (filePath && fs.existsSync(filePath)) {
                try {
                    fs.unlinkSync(filePath);
                    console.log(`[CLEANUP S3] Removido com sucesso: ${filePath}`);
                } catch (unlinkErr) {
                    console.error(`[CRITICAL S3] Falha ao remover arquivo temporário ${filePath}:`, unlinkErr);
                }
            }
        });
        if (outputPath && fs.existsSync(outputPath)) {
            try {
                fs.unlinkSync(outputPath);
                console.log(`[CLEANUP S3] Removido com sucesso: ${outputPath}`);
            } catch (unlinkErr) {
                console.error(`[CRITICAL S3] Falha ao remover arquivo de saída ${outputPath}:`, unlinkErr);
            }
        }
    };

    try {
        console.log('💻 [MIX ENGINE S3] Iniciando cruzamento S3 via API...');
        
        // 1. BAIXAR TODAS AS FAIXAS DO S3 PARA O /tmp
        console.log('[S3 PIPELINE] Baixando faixas do Bunker S3...');
        for (const s3Key of s3Keys) {
            try {
                const localPath = path.join('/tmp', `s3_${Date.now()}_${path.basename(s3Key)}`);
                const downloadCommand = new GetObjectCommand({ Bucket: BUCKET_NAME, Key: s3Key });
                const s3Response = await s3Client.send(downloadCommand);

                await new Promise((resolve, reject) => {
                    const fileStream = fs.createWriteStream(localPath);
                    s3Response.Body.pipe(fileStream);
                    s3Response.Body.on("error", err => reject(new Error(`Falha no stream do body S3 para ${s3Key}: ${err.message}`)));
                    fileStream.on("finish", resolve);
                    fileStream.on("error", err => reject(new Error(`Falha ao escrever no disco para ${s3Key}: ${err.message}`)));
                });
                localFilePaths.push(localPath);
                console.log(`[S3 PIPELINE] Baixada faixa ${s3Key} para ${localPath}`);
            } catch (downloadError) {
                console.error(`[CRITICAL S3] Falha ao baixar a faixa ${s3Key} do S3:`, downloadError);
                throw new Error(`Não foi possível baixar o arquivo ${s3Key} do S3. Verifique se o arquivo existe e se as permissões do IAM Role estão corretas.`);
            }
        }
        console.log('[S3 PIPELINE] Todas as faixas foram baixadas com sucesso.');

        const vignettePath = path.join(__dirname, '../../assets', 'VIGNETTE_MAIN.wav');
        if (!fs.existsSync(vignettePath)) {
            const errorMsg = `[CRITICAL S3] Arquivo de vinheta não encontrado no caminho esperado: ${vignettePath}. Verifique se a pasta 'assets' foi incluída no deploy.`;
            console.error(errorMsg);
            throw new Error(errorMsg);
        }
        console.log('[MIX ENGINE S3] Vinheta de ID encontrada com sucesso em:', vignettePath);

        let command = ffmpeg();
        command.input(vignettePath); // Canal 0
        localFilePaths.forEach(filePath => command.input(filePath)); // Canais 1 a N

        // 2. LÓGICA DE FILTRO COMPLEXO (Reutilizada e adaptada)
        let complexFilter = [];
        let lastOutput = '1:a';
        const fadeDurations = crossfades || [];

        if (localFilePaths.length > 1) {
            for (let i = 0; i < localFilePaths.length - 1; i++) {
                const nextInput = `${i + 2}:a`; // i+2 porque o input 0 é a vinheta, 1 é a primeira faixa
                const currentOutput = `xfade${i}`;
                const fadeDuration = parseFloat(fadeDurations[i]) || 8.0;

                console.log(`⚙️ Injetando transição S3 de ${fadeDuration}s entre Faixa ${i + 1} e Faixa ${i + 2}`);
                complexFilter.push({
                    filter: 'acrossfade',
                    options: { d: fadeDuration, curve: curva === 'equal-power' ? 'c1' : 'l' }, // Adapta curva
                    inputs: [lastOutput, nextInput],
                    outputs: currentOutput
                });
                lastOutput = currentOutput;
            }
        }
        
        complexFilter.push({ filter: 'adelay', options: '2000|2000', inputs: '0:a', outputs: 'vignette_delayed' });
        complexFilter.push({ filter: 'volume', options: '1.6', inputs: 'vignette_delayed', outputs: 'vignette_boosted' });
        complexFilter.push({
            filter: 'volume',
            options: "'if(lt(t,1.5),1,if(lt(t,2),1-(t-1.5)*1.5,if(lt(t,17),0.25,if(lt(t,19),0.25+(t-17)*0.375,1))))':eval=frame",
            inputs: lastOutput,
            outputs: 'music_ducked'
        });
        complexFilter.push({
            filter: 'amix',
            options: { inputs: 2, duration: 'longest', normalize: 0 },
            inputs: ['vignette_boosted', 'music_ducked'],
            outputs: 'final_master'
        });

        command.complexFilter(complexFilter, 'final_master');
        
        // Normalização de Loudness (Opcional)
        if (loudness === 'normalize') {
            command.audioFilter('loudnorm');
        }

        command
            .on('start', (cmdLine) => {
                console.log('⚙️ Compilando Setlist S3 com precisão cirúrgica...');
                console.log('[FFMPEG CMD]', cmdLine); // 🛡️ SRE: Log do comando FFMPEG exato
            })
            .on('end', async () => {
                console.log('💎 Deploy S3 Concluído! Enviando para o Bunker...');
                
                // 3. UPLOAD DO RESULTADO FINAL PARA O S3
                const masterS3Key = `setlists/${outputFileName}`;
                const fileBuffer = fs.readFileSync(outputFile);
                const uploadMasterCommand = new PutObjectCommand({
                    Bucket: BUCKET_NAME,
                    Key: masterS3Key,
                    Body: fileBuffer,
                    ContentType: "audio/wav"
                });
                await s3Client.send(uploadMasterCommand);
                console.log(`[SETLIST ENGINE] Master S3 enviada com sucesso: ${masterS3Key}`);

                // 4. GERAR URL DE DOWNLOAD ASSINADA
                const getCommand = new GetObjectCommand({
                    Bucket: BUCKET_NAME,
                    Key: masterS3Key,
                    ResponseContentDisposition: `attachment; filename="${outputFileName}"`
                });
                const downloadUrl = await getSignedUrl(s3Client, getCommand, { expiresIn: 900 });

                res.status(200).json({ success: true, downloadUrl: downloadUrl });

                // 5. LIMPEZA FINAL
                cleanup(localFilePaths, outputFile);
            })
            .on('error', (err, stdout, stderr) => { // 🛡️ SRE: Captura stdout/stderr do ffmpeg [1.3.1]
                console.error('\n🛡️ Falha Crítica no Pipeline S3 do FFMPEG:', err.message);
                console.error('FFMPEG STDOUT:', stdout);
                console.error('FFMPEG STDERR:', stderr);
                cleanup(localFilePaths, outputFile);
                if (!res.headersSent) res.status(500).json({ error: 'Falha na renderização da Setlist S3.', ffmpegError: stderr });
            })
            .save(outputFile);

    } catch (error) {
        console.error('[CRITICAL S3] Colapso geral no motor de mixagem S3:', error.message);
        cleanup(localFilePaths, outputFile);
        if (!res.headersSent) res.status(500).json({ error: 'Erro interno no motor S3.', details: error.message });
    }
});


// ============================================================================
// ROTA ANTIGA: POST /mix/generate (Legado, para testes locais)
// ============================================================================
router.post('/generate', upload.array('tracks', 20), (req, res) => {
    const uploadedFiles = req.files || [];
    const outputFileName = `RQS_SETLIST_${Date.now()}.wav`;
    const outputDir = '/tmp/'; // 🛡️ Diretório efêmero de escrita do Lambda/Serverless
    const outputFile = path.join(outputDir, outputFileName);

    // Função de Limpeza de Emergência (Higienização de Disco)
    const cleanup = (filesToClean, outputPath) => {
        filesToClean.forEach(f => {
            if (f && f.path && fs.existsSync(f.path)) {
                try {
                    fs.unlinkSync(f.path);
                    console.log(`[CLEANUP] Removido com sucesso: ${f.path}`);
                } catch (unlinkErr) {
                    console.error(`[CRITICAL] Falha ao remover arquivo temporário ${f.path}:`, unlinkErr);
                }
            }
        });
        if (outputPath && fs.existsSync(outputPath)) {
            try {
                fs.unlinkSync(outputPath);
                console.log(`[CLEANUP] Removido com sucesso: ${outputPath}`);
            } catch (unlinkErr) {
                console.error(`[CRITICAL] Falha ao remover arquivo de saída ${outputPath}:`, unlinkErr);
            }
        }
    };

    try {
        console.log('💻 [MIX ENGINE] Iniciando cruzamento ponto-a-ponto via API...');

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

        // ====================================================================
        // 4. PROTOCOLO DE SOBREPOSIÇÃO (AUTO-DUCKING DINÂMICO ESTILO RÁDIO FM) [1]
        // ====================================================================
        
        // Atraso de 2 segundos para o início da locução do locutor
        complexFilter.push({
            filter: 'adelay',
            options: '2000|2000',
            inputs: '0:a',
            outputs: 'vignette_delayed'
        });

        // Ganho de presença na voz da vinheta para cortar a mixagem pesada
        complexFilter.push({
            filter: 'volume',
            options: '1.6', // Ganho de +4dB na vinheta para sobressair
            inputs: 'vignette_delayed',
            outputs: 'vignette_boosted'
        });

        // ENVELOPE DE VOLUME DINÂMICO (AUTO-DUCKING) NO CANAL DE MÚSICA [1.2]
        // Lógica Matemática do Filtro:
        // - t < 1.5s: Volume total em 100% (1.0)
        // - t 1.5s a 2.0s: Fade-down suave de 0.5s para 25% (0.25)
        // - t 2.0s a 17.0s: Mantém em 25% enquanto o locutor de 15s fala
        // - t 17.0s a 19.0s: Fade-up suave de 2.0s de volta para 100% (1.0)
        // - t > 19.0s: Mantém em 100% do volume pelo resto de TODA a setlist!
       complexFilter.push({
            filter: 'volume',
            options: "'if(lt(t,1.5),1,if(lt(t,2),1-(t-1.5)*1.5,if(lt(t,17),0.25,if(lt(t,19),0.25+(t-17)*0.375,1))))':eval=frame",
            inputs: lastOutput,
            outputs: 'music_ducked'
        });

        // Mixagem final limpa somando os dois canais processados
        complexFilter.push({
            filter: 'amix',
            options: { inputs: 2, duration: 'longest', normalize: 0 },
            inputs: ['vignette_boosted', 'music_ducked'],
            outputs: 'final_master'
        });

        command.complexFilter(complexFilter, 'final_master');

        command
            .on('start', () => console.log('⚙️ Compilando Setlist com precisão cirúrgica...'))
            .on('end', () => {
                console.log('💎 Deploy Concluído! Transmitindo...');
                res.download(outputFile, outputFileName, (downloadErr) => {
                    if (downloadErr) {
                        console.error('[CRITICAL] Falha no download do cliente:', downloadErr);
                    }
                    // Limpeza completa de todos os arquivos temporários após o sucesso ou falha do download.
                    cleanup(uploadedFiles, outputFile);
                });
            })
            .on('error', (err) => {
                console.error('\n🛡️ Falha Crítica no Pipeline:', err.message);
                // Protocolo SRE: Limpa o disco em caso de falha de renderização.
                cleanup(uploadedFiles, outputFile);
                if (!res.headersSent) {
                    res.status(500).json({ error: 'Falha na renderização da Setlist.' });
                }
            })
            .save(outputFile);

    } catch (error) {
        console.error('[CRITICAL] Colapso geral:', error);
        // Protocolo SRE: Limpa o disco em caso de colapso geral da API.
        cleanup(uploadedFiles, outputFile);
        if (!res.headersSent) {
            res.status(500).json({ error: 'Erro interno no motor.' });
        }
    }
});

module.exports = router;