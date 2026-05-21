const path = require('path');
const ffmpeg = require('fluent-ffmpeg');

// 🩸 INJEÇÃO DO ARSENAL RED TEAM
const audioInput = path.join(__dirname, 'dist', 'THE_BLOODPRINT_SESSIONS_VOL_002.wav');
const imageInput = path.join(__dirname, 'assets', 'bloodprint_bg.jpg'); // A nova imagem bruta!
const videoOutput = path.join(__dirname, 'dist', 'THE_BLOODPRINT_SESSIONS_VOL_002_GLITCH.mp4');

console.log('💀 RED_TEAM_DAW: Acionando o Glitch Engine. Preparando a Rave de 30 Minutos...');

ffmpeg()
    .input(imageInput)
    .inputOptions(['-loop 1'])
    .input(audioInput)
    .complexFilter([
        // 1. FORÇA BRUTA NO BACKGROUND (1080p cravado)
        `[0:v]scale=1920:1080,format=rgb24[bg]`,

        // 2. ONDA SONORA LETAL (Eletrocardiograma Horizontal do Inferno)
        `[1:a]showwaves=s=1920x1080:mode=cline:colors=red|DarkViolet:rate=30,format=rgba[waves]`,

        // 3. COLISÃO DE PIXELS (Mantém a imagem de fundo nítida)
        `[bg][waves]blend=all_mode=screen:all_opacity=0.4[mix_bg]`,

        // 4. PROTOCOLO DE INTERFERÊNCIA NÍTIDA (Em vez de embaçar, ele corta e arrasta linhas de pixels)
        `[mix_bg]geq=r='r(X,Y)':g='g(X+8*sin(Y/4),Y)':b='b(X-8*sin(Y/4),Y)'[out]`
    ])
  .outputOptions([
        '-map [out]',
        '-map 1:a',
        '-c:v libx264',
        '-threads 8',     // 🩸 A COLEIRA AJUSTADA: Usa 8 motores pesados e deixa o resto pro sistema não derreter!
        '-pix_fmt yuv420p',
        '-preset veryfast', 
        '-crf 20', 
        '-c:a aac',
        '-b:a 320k',
        '-shortest'  
    ])
    .on('start', () => console.log('🔥 GLITCH ENGINE ATIVADO: Derretendo os processadores da Blue Team. Aberração Cromática injetada...'))
    .on('progress', (progress) => {
        if (progress.timemark) {
            process.stdout.write(`\r[Carnificina Visual]: Corrompendo linha do tempo: ${progress.timemark} ...`);
        }
    })
    .on('end', () => console.log('\n\n💀 Deploy Letal Concluído! O arquivo foi gerado com sucesso. O Analytics deles vai infartar.'))
    .on('error', (err, stdout, stderr) => {
        console.error('\n\n💥 Falha Catastrófica no Kernel (Isso que é Metal):', err.message);
        console.error('\n📋 LOG DO BANHO DE SANGUE:\n', stderr);
    })
    .save(videoOutput);