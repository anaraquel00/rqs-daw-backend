const path = require('path');
const ffmpeg = require('fluent-ffmpeg');

// ⚠️ ATENÇÃO: Aponte para o arquivo ÚNICO de 1h15m que você consolidou
const audioInput = path.join(__dirname, 'dist', 'THE_BLUEPRINT_SESSIONS_VOL_005.wav');
// ⚠️ ATENÇÃO: Faça uma capa nova e épica para o Vol 005
const imageInput = path.join(__dirname, 'bg-vol005.jpg'); 
const videoOutput = path.join(__dirname, 'dist', 'THE_BLUEPRINT_SESSIONS_VOL_005_FINAL.mkv');

// 🛡️ Coordenadas da Onda (Holograma RQS)
// Calibrado e Homologado para o Monitor de Canto do Vol. 005
const tvWidth = 838;    // Reduzimos a largura para encaixar no painel
const tvHeight = 250;   // Ajustamos a altura para não vazar a borda
const tvX = 1780;       // Posicionamento X (Horizontal) movido para a direita
const tvY = 1130;        // Posicionamento Y (Vertical) alinhado com a console inferior

console.log('💻 RQS_DAW: A iniciar DEPLOY DO MONÓLITO (75 Minutos)...');
console.log('⚠️ AVISO: A CPU entrará em uso extremo. Não feche o terminal.');

ffmpeg()
    .input(imageInput)
    .inputOptions(['-loop 1'])
    .input(audioInput)
    .complexFilter([
        // 1. Normalização cravada
        `[0:v]scale=trunc(iw/2)*2:trunc(ih/2)*2,format=rgb24[bg]`,
        // 2. Onda Visual com multiplicador 5.0 (Volume)
        `[1:a]volume=5.0,showfreqs=mode=bar:fscale=log:s=${tvWidth}x${tvHeight}:colors=cyan|cyan:ascale=log,format=rgba,colorkey=black:0.1:0.2[waves]`,
        // 3. Sobreposição Holográfica
        `[bg][waves]overlay=x=${tvX}:y=${tvY}:shortest=1[out]`
    ])
    .outputOptions([
        '-map [out]',
        '-map 1:a',
        '-c:v libx264',
        //'-t 15',            
        '-r 24',            // 🛡️ PATCH DE HARDWARE: 24 FPS para poupar a CPU
        '-preset fast',     // Equilíbrio entre tamanho final e velocidade
        '-crf 23',          // Qualidade visual constante
        '-threads 0',       // 🛡️ Sequestra todos os núcleos do processador
        '-pix_fmt yuv420p',
        '-c:a copy'         // Soberania absoluta: Mantém os 800MB do WAV intactos
    ])
    .on('start', () => console.log('⚙️ Compilação iniciada. Acionando dissipadores do chassi...'))
    .on('progress', (progress) => {
        if (progress.timemark) {
            process.stdout.write(`\r[Renderização V5]: Compilando linha do tempo: ${progress.timemark} ...`);
        }
    })
    .on('end', () => console.log('\n\n💎 Deploy Absoluto Concluído! O monólito VOL_005 está pronto.'))
    .on('error', (err, stdout, stderr) => {
        console.error('\n\n🛡️ Falha Catastrófica no Kernel:', err.message);
        console.error('\n📋 LOG CAIXA PRETA:\n', stderr);
    })
    .save(videoOutput);