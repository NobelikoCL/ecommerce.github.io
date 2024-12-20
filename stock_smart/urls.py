from django.urls import path, include
from . import views
from django.views.decorators.csrf import csrf_exempt
from .views import PaymentSuccessView
import logging
import hmac
import hashlib
import json
import requests

logger = logging.getLogger(__name__)

app_name = 'stock_smart'

urlpatterns = [
    # Páginas principales
    path('', views.productos_lista, name='productos_lista'),
    path('products/', views.productos_lista, name='products'),
    path('about/', views.about, name='about'),
    path('contacto/', views.contacto, name='contacto'),
    path('terminos/', views.TerminosView.as_view(), name='terminos'),
   
    
    # Autenticación
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('register/', views.register_view, name='register'),
    path('profile/', views.profile, name='profile'),
    
    # Carrito y proceso de compra múltiple
    path('cart/', views.cart_view, name='cart_view'),
    path('cart/', views.cart_view, name='cart'),
    path('cart/add/', views.add_to_cart, name='add_to_cart'),
    path('cart/remove/', views.remove_from_cart, name='remove_from_cart'),
    path('cart/update/', views.update_cart, name='cart_update'),
    path('cart/checkout/', views.CheckoutOptionsView.as_view(), name='checkout_options'),
    path('cart/payment/', views.cart_payment, name='cart_payment'),
    path('cart/confirm/', views.cart_confirm, name='cart_confirm'),
    path('cart/update/<int:product_id>/', views.cart_update, name='cart_update'),
    
    # Compra directa (un solo producto)
    path('buy-now/<int:product_id>/', views.buy_now, name='buy_now'),
    path('buy-now/checkout/<int:product_id>/', views.buy_now_checkout, name='buy_now_checkout'),
    path('buy-now/payment/<int:product_id>/', views.buy_now_payment, name='buy_now_payment'),
    path('buy-now/confirm/<int:product_id>/', views.buy_now_confirm, name='buy_now_confirm'),
    
    # API endpoints para carrito
    path('api/cart/update/', views.update_cart_api, name='update_cart_api'),
    
    # Proceso de compra
    path('checkout/options/', views.checkout_options, name='checkout_options'),
    path('checkout/', views.guest_checkout, name='guest_checkout'),
    path('checkout/process-payment/', views.process_payment, name='process_payment'),
    path('checkout/process-guest-order/', views.process_guest_order, name='process_guest_order'),
    path('checkout/flow-payment/<int:order_id>/', views.flow_payment, name='flow_payment'),
    path('checkout/transfer-instructions/<int:order_id>/', views.transfer_instructions, name='transfer_instructions'),
    path('checkout/flow/confirm/', views.flow_confirm, name='flow_confirm'),
    path('checkout/flow/return/', views.flow_return, name='flow_return'),
    path('checkout/process-flow-payment/', views.process_flow_payment, name='process_flow_payment'),
    path('payment/confirm/', views.flow_confirm, name='flow_confirm'),
    path('payment/return/', views.flow_return, name='flow_return'),
    path('payment/notify/', views.payment_notify, name='payment_notify'),
    path('payment/success/', views.payment_success, name='payment_success'),
    path('payment/cancel/', views.payment_cancel, name='payment_cancel'),
    path('payments/', include('payments.urls')),
    
    # URLs para Flow
    path('flow/confirm/', csrf_exempt(views.flow_confirm), name='flow_confirm'),
    path('flow/return/', views.flow_return, name='flow_return'),
    path('checkout/<int:product_id>/', views.checkout_options, name='checkout'),
    path('checkout/guest/<int:product_id>/', views.checkout_guest, name='checkout_guest'),
    # Checkout rápido (un solo producto)
    path('checkout/<int:product_id>/', views.checkout_options, name='checkout'),
    # Checkout para usuarios registrados
    path('checkout/user/', views.user_checkout, name='user_checkout'),
    # Checkout para invitados
    path('checkout/guest/', views.guest_checkout, name='guest_checkout'),
    
    # Nuevas rutas para carrito
    path('cart/checkout/', views.cart_checkout_options, name='cart_checkout_options'),
    path('cart/checkout/user/', views.user_cart_checkout, name='user_cart_checkout'),
    path('cart/checkout/guest/', views.guest_cart_checkout, name='guest_cart_checkout'),
    path('api/validate-product/<int:product_id>/', views.validate_product, name='validate_product'),
    path('checkout/options/<int:product_id>/', views.checkout_options, name='checkout_options'),
    path('checkout/guest/', views.guest_checkout, name='guest_checkout'),
    path('checkout/process-payment/', views.process_payment, name='process_payment'),
    path('payment/success/', views.payment_success, name='payment_success'),
    path('payment/cancel/', views.payment_cancel, name='payment_cancel'),
    path('payment/confirm/', views.payment_confirm, name='payment_confirm'),
    path('producto/<int:producto_id>/', views.detalle_producto, name='detalle_producto'),
    path('checkout/<int:producto_id>/', views.iniciar_checkout, name='iniciar_checkout'),
    path('checkout/process-payment/', views.process_payment, name='process_payment'),
    path('checkout/payment-success/', csrf_exempt(PaymentSuccessView.as_view()), name='payment_success'),
    path('checkout/payment-confirm/', views.payment_confirm, name='payment_confirm'),
    path('checkout/payment-error/', views.payment_error, name='payment_error'),
    path('categoria/<int:category_id>/', views.category_detail, name='category_detail'),
    path('categoria/<slug:slug>/', views.productos_por_categoria, name='productos_por_categoria'),
    path('productos/', views.ProductosListaView.as_view(), name='productos_lista'),
    # Compra rápida (existente)
    path('checkout/options/<int:product_id>/', views.CheckoutOptionsView.as_view(), name='checkout_options'),
    # Checkout del carrito (nueva)
    path('cart/checkout/options/', views.CartOptionsCheckoutView.as_view(), name='cart_options_checkout'),
    path('cart/checkout/guest/', views.GuestCartCheckoutView.as_view(), name='guest_cart_checkout'),
    path('cart/checkout/process/', views.ProcessCartCheckoutView.as_view(), name='process_cart_checkout'),
    path('cart/checkout/payment/', views.CartPaymentView.as_view(), name='cart_payment'),
    path('cart/checkout/confirm/', views.CartPaymentConfirmView.as_view(), name='cart_payment_confirm'),
    path('checkout/payment/', views.payment_form, name='payment_form'),
        path('checkout/transfer-instructions/<int:order_id>/', 
         views.transfer_instructions, 
         name='transfer_instructions'),
    path('payment/process/', views.process_payment, name='process_payment'),
    path('payment/confirm/', views.payment_confirm, name='payment_confirm'),
    path('payment/success/', views.payment_success, name='payment_success'),
    path('payment/mercadopago/success/', views.mercadopago_success, name='mercadopago_success'),
    path('payment/mercadopago/failure/', views.mercadopago_failure, name='mercadopago_failure'),
    path('payment/mercadopago/pending/', views.mercadopago_pending, name='mercadopago_pending'),
    path('payment/mercadopago/webhook/', views.mercadopago_webhook, name='mercadopago_webhook'),
    path('payment/mercadopago/create/', views.mercadopago_create_preference, name='mercadopago_create_preference'),
    # URLs para MercadoPago
    path('payment/success/', views.payment_success, name='payment_success'),
    path('payment/failure/', views.payment_failure, name='payment_failure'),
    path('payment/pending/', views.payment_pending, name='payment_pending'),
    path('payment/mercadopago/webhook/', views.mercadopago_webhook, name='mercadopago_webhook'),
    path('categoria/<slug:slug>/', views.productos_por_categoria, name='productos_por_categoria'),
]

logger.info("URLs del carrito configuradas correctamente")
