// src/controllers/payment.js

const express = require('express');
const router = express.Router();
const { createClient } = require('@supabase/supabase-js');

const stripe = require('stripe')(
  process.env.STRIPE_SECRET_KEY
);

const supabaseAdmin = createClient(
  process.env.SUPABASE_URL,
  process.env.SUPABASE_SECRET_KEY,
  {
    auth: {
      persistSession: false
    }
  }
);

const endpointSecret =
  process.env.STRIPE_WEBHOOK_SECRET;

router.post(
  '/stripe-webhook',
  async (req, res) => {

    const sig =
      req.headers['stripe-signature'];

    let event;

    try {

      event =
        stripe.webhooks.constructEvent(
          req.rawBody,
          sig,
          endpointSecret
        );

    } catch (err) {

      console.error(
        '[STRIPE ERROR] Falha ao validar assinatura do webhook:',
        err.message
      );

      return res
        .status(400)
        .send(
          `Webhook Error: ${err.message}`
        );
    }


    if (
      event.type ===
      'checkout.session.completed'
    ) {

      const session =
        event.data.object;

      const userEmail =
        session.customer_details?.email
          ?.trim()
          ?.toLowerCase();


      if (!userEmail) {

        console.error(
          '[STRIPE PAY] Checkout concluído sem e-mail do usuário.'
        );

        return res
          .status(400)
          .json({
            received: false
          });
      }


      try {

        const {
          error
        } =
          await supabaseAdmin
            .from('profiles')
            .update({
              role: 'premium'
            })
            .eq(
              'email',
              userEmail
            );


        if (error) {

          console.error(
            '[CRITICAL] Falha ao atualizar perfil:',
            error
          );

          return res
            .status(500)
            .json({
              received: false
            });
        }


        console.log(
          '[STRIPE PAY] Perfil promovido para PREMIUM.'
        );

      } catch (dbError) {

        console.error(
          '[CRITICAL] Erro de conexão com Supabase:',
          dbError
        );

        return res
          .status(500)
          .json({
            received: false
          });
      }
    }


    return res
      .status(200)
      .json({
        received: true
      });
  }
);

module.exports = router;