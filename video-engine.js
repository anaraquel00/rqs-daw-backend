const path = require('path');
const ffmpeg = require('fluent-ffmpeg');

const audioInput = path.join(__dirname, 'dist', 'THE_BLUEPRINT_SESSIONS_VOL_007.mp3');
const imageInput = path.join(__dirname, 'bg-video.jpg');
const videoOutput = path.join(__dirname, 'dist', 'TESTE_VISUAL_15_SEGUNDOS.mp4');

// 🛡️ As tuas coordenadas da TV mantêm-se intactas
const tvWidth = 800;
const tvHeight = 400;
const tvX = 560;
const tvY = 340;

console.log('💻 RQS_DAW: A iniciar Patch V5.0 (Isolamento de Cor e Overlay Direto)...');

ffmpeg()
    .input(imageInput)
    .inputOptions(['-loop 1'])
    .input(audioInput)
    .complexFilter([
        // 1. Gera as ondas em ciano puro e converte IMEDIATAMENTE para RGBA (Canal Transparente).
        // O 'colorkey' desintegra o fundo preto das ondas antes de tocar na tua arte.
        `[1:a]showfreqs=mode=bar:s=${tvWidth}x${tvHeight}:colors=cyan|cyan:ascale=log,format=rgba,colorkey=black:0.1:0.2[waves]`,

        // 2. 💎 Overlay Direto: Cola as ondas por cima da imagem original nas coordenadas da TV.
        // Zero alteração nas cores do teu background!
        `[0:v][waves]overlay=x=${tvX}:y=${tvY}[out]`
    ])
    .outputOptions([
        '-map [out]',
        '-map 1:a',
        '-t 15',            // 🛡️ Kill Switch de 15 segundos ativado para validação rápida
        '-c:v libx264',
        '-pix_fmt yuv420p', // Apenas converte para o padrão do YouTube na saída final
        '-preset ultrafast',
        '-c:a copy'
    ])
    .on('start', () => console.log('⚙️ A compilar a matriz de sobreposição. A preservar cores originais...'))
    .on('end', () => console.log('\n💎 Injeção limpa concluída! Verifica o ficheiro TESTE_VISUAL_15_SEGUNDOS.mp4.'))
    .on('error', (err) => console.error('\n🛡️ Erro no Kernel:', err.message))
    .save(videoOutput);
