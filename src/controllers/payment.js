'use strict';

const express = require('express');
const { getPaymentMode } = require('../lib/runtime-config');
const router = express.Router();

function requireEnv(name) {
  const value = process.env[name];
  if (!value || !String(value).trim()) {
    throw new Error(`Server configuration missing: ${name}`);
  }
  return String(value).trim();
}

const paymentMode = getPaymentMode();

if (paymentMode === 'disabled') {
  router.use((req, res) => res.status(503).json({
    error: 'Payment integration is disabled in this environment.',
    code: 'PAYMENT_DISABLED',
  }));
} else {
  const stripe = require('stripe')(requireEnv('STRIPE_SECRET_KEY'));

  async function promoteProfileToPremium(userEmail) {
    const supabaseUrl = requireEnv('SUPABASE_URL').replace(/\/+$/, '');
    const secretKey = requireEnv('SUPABASE_SECRET_KEY');

    const headers = {
      apikey: secretKey,
      'Content-Type': 'application/json',
      Prefer: 'return=minimal',
    };

    if (secretKey.split('.').length === 3) {
      headers.Authorization = `Bearer ${secretKey}`;
    }

    const response = await fetch(
      `${supabaseUrl}/rest/v1/profiles?email=eq.${encodeURIComponent(userEmail)}`,
      {
        method: 'PATCH',
        headers,
        body: JSON.stringify({ role: 'premium' }),
      },
    );

    if (!response.ok) {
      throw new Error(`Supabase profile update failed with HTTP ${response.status}.`);
    }
  }

  router.post('/stripe-webhook', async (req, res) => {
    const sig = req.headers['stripe-signature'];

    let event;
    try {
      event = stripe.webhooks.constructEvent(
        req.rawBody,
        sig,
        requireEnv('STRIPE_WEBHOOK_SECRET'),
      );
    } catch (err) {
      console.error('[STRIPE ERROR] Falha ao validar assinatura do webhook:', err.message);
      return res.status(400).send(`Webhook Error: ${err.message}`);
    }

    if (event.type === 'checkout.session.completed') {
      const session = event.data.object;
      const userEmail = session.customer_details?.email?.trim()?.toLowerCase();

      if (!userEmail) {
        console.error('[STRIPE PAY] Checkout concluído sem e-mail do usuário.');
        return res.status(400).json({ received: false });
      }

      try {
        await promoteProfileToPremium(userEmail);
        console.log('[STRIPE PAY] Perfil promovido para PREMIUM.');
      } catch (error) {
        console.error('[CRITICAL] Falha ao atualizar perfil Premium:', error.message);
        return res.status(500).json({ received: false });
      }
    }

    return res.status(200).json({ received: true });
  });
}

module.exports = router;
