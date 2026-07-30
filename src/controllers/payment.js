// src/controllers/payment.js
const express = require('express');
const router = express.Router();
const { createClient } = require('@supabase/supabase-js');
const stripe = require('stripe')('sk_test_51RvPs80vU1EZjW1G9ox6LBQpKUuljEAuDM4kWHz6ZQX4Bu9haOz8n8MamX11gq8afDJtdgo6SWRnouynUldNgCOD00C9LnVFkH'); // ⚠️ Substitua pela sua sk_test da Stripe

// Inicializa o cliente administrativo do Supabase usando a sua SERVICE_ROLE_KEY
const supabaseAdmin = createClient(
  'https://ucearnthodrltkvkmhit.supabase.co',
  'sb_secret_zzpzxNivmpASr9P23IWU3A_qFgq6hpV',
  {
    auth: {
      persistSession: false // Prática recomendada em ambientes SRE/Serverless
    }
  }
);

// Segredo do Webhook gerado na aba Webhooks do seu painel da Stripe (ex: whsec_...) [1.1.8]
const endpointSecret = 'whsec_rNEiVvlF4REHTG4Ehs0oXj3VssOx2c9A'; 

router.post('/stripe-webhook', (req, res) => {
  const sig = req.headers['stripe-signature'];
  let event;

  try {
    // 🟢 SEGURANÇA SRE: Usa o buffer bruto salvo no req.rawBody para validar a assinatura! [1]
    event = stripe.webhooks.constructEvent(req.rawBody, sig, endpointSecret);
  } catch (err) {
    console.error(`[STRIPE ERROR] Falha ao validar assinatura do Webhook:`, err.message);
    return res.status(400).send(`Webhook Error: ${err.message}`);
  }

  // Escuta a aprovação do pagamento do checkout de assinatura [1.1.8]
  if (event.type === 'checkout.session.completed') {
    const session = event.data.object;
    const userEmail = session.customer_details.email;

    console.log(`[STRIPE PAY] Assinatura aprovada com sucesso para: ${userEmail}`);

    // 🟢 UPGRADE SRE: Promove o usuário para PREMIUM diretamente no banco Postgres [1]
    supabaseAdmin
      .from('profiles')
      .update({ role: 'premium' })
      .eq('email', userEmail)
      .then(({ error }) => {
        if (error) {
          console.error("[CRITICAL] Falha ao atualizar papel no Supabase:", error);
        } else {
          console.log(`[STRIPE PAY] Usuário ${userEmail} promovido para PREMIUM no banco de dados!`);
        }
      });
  }

  res.status(200).json({ received: true });
});

module.exports = router;