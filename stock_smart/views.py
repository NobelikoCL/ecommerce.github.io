from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils.crypto import get_random_string
from django.db.models import Q
from django.http import JsonResponse, HttpResponse, FileResponse
from django.views.decorators.http import require_POST, require_http_methods
from django.core.paginator import Paginator
from django.views.decorators.csrf import ensure_csrf_cookie, csrf_exempt, csrf_protect
from .forms import RegisterForm, GuestCheckoutForm, UserProfileForm, CustomUserCreationForm
from .models import CustomUser, Product, Category, Cart, CartItem, Order, FlowCredentials, OrderTracking, OrderItem, GuestOrder, GuestOrderItem
import json
from decimal import Decimal
from django.utils import timezone
from django.core.mail import EmailMessage, send_mail
from django.conf import settings
from .services.flow_service import FlowPaymentService
import uuid
from django.contrib.humanize.templatetags.humanize import intcomma
import requests
from django.urls import reverse
import hashlib
import hmac
from datetime import datetime
import logging
import traceback
from django.urls import reverse
from django.core.exceptions import ObjectDoesNotExist
from payments import get_payment_model, PaymentStatus, RedirectNeeded
from django.conf import settings
from django.views.generic import ListView
from django.views import View
from django.core.exceptions import ValidationError
from django import forms
import time
from django.db import connection
from django.utils.decorators import method_decorator
from .adapters.mercadopago_adapter import MercadoPagoAdapter
from django.db import models



logger = logging.getLogger(__name__)
Payment = get_payment_model()
logger = logging.getLogger('django.security')

def get_cart_count(request):
    if request.user.is_authenticated:
        cart = Cart.objects.filter(user=request.user).first()
        return cart.get_total_items() if cart else 0
    else:
        return len(request.session.get('cart', {}))

def index(request):
    offer_products = Product.objects.filter(discount_percentage__gt=0, active=True)[:8]
    featured_products = Product.objects.filter(active=True)[:8]
    
    context = {
        'offer_products': offer_products,
        'featured_products': featured_products,
        'main_categories': Category.objects.filter(parent=None, is_active=True)
    }
    return render(request, 'stock_smart/home.html', context)

def register_view(request):
    try:
        logger.info("="*50)
        logger.info("INICIO REGISTRO DE USUARIO")
        logger.info("Verificando imports y formulario")
        logger.info(f"CustomUserCreationForm está disponible: {CustomUserCreationForm}")
        
        if request.method == 'POST':
            form = CustomUserCreationForm(request.POST)
            logger.info(f"Datos del formulario: {request.POST}")
            
            if form.is_valid():
                logger.info("Formulario válido - Creando usuario")
                user = form.save()
                login(request, user)
                logger.info(f"Usuario creado y logueado: {user.username}")
                messages.success(request, '¡Registro exitoso!')
                return redirect('/')
            else:
                logger.error(f"Errores en el formulario: {form.errors}")
                messages.error(request, 'Error en el registro. Por favor, verifica los datos.')
        else:
            form = CustomUserCreationForm()
            logger.info("Mostrando formulario de registro vacío")
        
        return render(request, 'stock_smart/register.html', {'form': form})
        
    except Exception as e:
        logger.error("ERROR EN REGISTRO DE USUARIO")
        logger.error(f"Error: {str(e)}")
        logger.error(f"Traceback completo: {traceback.format_exc()}")
        messages.error(request, 'Error al procesar el registro')
        return redirect('/')

def login_view(request):
    try:
        logger.info("="*50)
        logger.info("INICIO LOGIN")
        
        if request.method == 'POST':
            email = request.POST.get('email')
            password = request.POST.get('password')
            logger.info(f"Intento de login con email: {email}")
            
            try:
                user = CustomUser.objects.get(email=email)
                user = authenticate(request, username=user.username, password=password)
                
                if user is not None:
                    login(request, user)
                    logger.info(f"Login exitoso para usuario: {email}")
                    messages.success(request, '¡Bienvenido!')
                    return redirect('/')
                else:
                    logger.warning(f"Credenciales inválidas para: {email}")
                    messages.error(request, 'Credenciales inválidas')
            except CustomUser.DoesNotExist:
                logger.warning(f"Usuario no encontrado: {email}")
                messages.error(request, 'Usuario no encontrado')
        
        return render(request, 'stock_smart/login.html')
        
    except Exception as e:
        logger.error("ERROR EN LOGIN")
        logger.error(f"Error: {str(e)}")
        logger.error(traceback.format_exc())
        messages.error(request, 'Error al procesar el login')
        return redirect('/')

def about_view(request):
    return render(request, 'stock_smart/about.html')

def contact_view(request):
    return render(request, 'stock_smart/contacto.html')

def terms_view(request):
    return render(request, 'stock_smart/terminos.html')


def help_view(request):
    return render(request, 'stock_smart/ayuda.html')

def category_view(request, slug):
    category = get_object_or_404(Category, slug=slug, is_active=True)
    
    # Obtener productos de la categoría
    products = Product.objects.filter(
        category=category,
        stock__gt=0
    ).order_by('-created_at')
    
    # Obtener categorías para el mega menú
    main_categories = Category.objects.filter(
        parent__isnull=True,
        is_active=True
    ).prefetch_related('children')
    
    context = {
        'category': category,
        'products': products,
        'main_categories': main_categories,
    }
    return render(request, 'stock_smart/category.html', context)


def products(request):
    products_list = Product.objects.all()
    
    # B��squeda
    query = request.GET.get('q')
    if query:
        products_list = products_list.filter(
            Q(name__icontains=query) |
            Q(description__icontains=query)
        )  # Aquí faltaba cerrar el paréntesis
    
    # Ordenamiento
    order = request.GET.get('order')
    if order:
        if order == 'price_asc':
            products_list = products_list.order_by('price')
        elif order == 'price_desc':
            products_list = products_list.order_by('-price')
        elif order == 'name':
            products_list = products_list.order_by('name')
    
    # Paginación
    paginator = Paginator(products_list, 9)  # 9 productos por página
    page = request.GET.get('page')
    products = paginator.get_page(page)
    
    context = {
        'products': products,
    }
    return render(request, 'stock_smart/products.html', context)

def buy_now_checkout(request, product_id):
    """Checkout para compra directa de un producto"""
    product = get_object_or_404(Product, id=product_id)
    
    # Calcular totales
    subtotal = product.final_price
    iva = subtotal * Decimal('0.19')
    total = subtotal + iva
    
    context = {
        'is_buy_now': True,
        'product': product,
        'subtotal': subtotal,
        'iva': iva,
        'total': total,
    }
    
    return render(request, 'stock_smart/checkout_options.html', context)


def checkout_options(request, product_id=None):
    if product_id:
        try:
            # Obtener el producto
            product = get_object_or_404(Product, id=product_id)
            
            # Debug del producto
            logger.debug("="*50)
            logger.debug("INFORMACIÓN DEL PRODUCTO")
            logger.debug(f"ID: {product.id}")
            logger.debug(f"Nombre: {product.name}")
            logger.debug(f"Precio publicado: {product.published_price}")
            logger.debug(f"Tipo de precio publicado: {type(product.published_price)}")
            logger.debug(f"Descuento %: {product.discount_percentage}")
            logger.debug(f"Tipo de descuento: {type(product.discount_percentage)}")
            
            # Calcular valores
            precio_original = Decimal(str(product.published_price))
            
            # Debug de cálculos
            logger.debug("\nCÁLCULOS DE PRECIOS")
            logger.debug(f"Precio original: {precio_original}")
            
            # Calcular descuento
            if product.discount_percentage and product.discount_percentage > 0:
                descuento_decimal = Decimal(str(product.discount_percentage)) / Decimal('100')
                descuento_monto = precio_original * descuento_decimal
                precio_con_descuento = precio_original - descuento_monto
                
                logger.debug(f"Descuento decimal: {descuento_decimal}")
                logger.debug(f"Monto descuento: {descuento_monto}")
            else:
                descuento_monto = Decimal('0')
                precio_con_descuento = precio_original
                
                logger.debug("No hay descuento aplicado")
            
            # Calcular IVA y total
            iva = precio_con_descuento * Decimal('0.19')
            total = precio_con_descuento + iva
            
            logger.debug(f"Precio con descuento: {precio_con_descuento}")
            logger.debug(f"IVA: {iva}")
            logger.debug(f"Total: {total}")
            logger.debug("="*50)
            
            # También imprimir en consola para desarrollo
            print("\n=== DEBUG INFORMACIÓN PRODUCTO ===")
            print(f"ID: {product.id}")
            print(f"Nombre: {product.name}")
            print(f"Precio publicado: {product.published_price}")
            print(f"Descuento %: {product.discount_percentage}")
            print(f"\n=== CÁLCULOS ===")
            print(f"Precio original: {precio_original}")
            print(f"Descuento: {descuento_monto}")
            print(f"Precio con descuento: {precio_con_descuento}")
            print(f"IVA: {iva}")
            print(f"Total: {total}")
            print("="*30)

            context = {
                'product': product,
                'precio_original': precio_original,
                'descuento': descuento_monto,
                'precio_con_descuento': precio_con_descuento,
                'iva': iva,
                'total': total,
                'cart_count': get_cart_count(request),
            }
            
            return render(request, 'stock_smart/checkout_options.html', context)
            
        except Exception as e:
            logger.error(f"Error en checkout_options: {str(e)}")
            print(f"Error en checkout_options: {str(e)}")
            return redirect('stock_smart:home')
    
    return redirect('stock_smart:home')

def process_payment(request):
    try:
        logger.info("="*50)
        logger.info("INICIANDO PROCESO DE PAGO FLOW SANDBOX")
        
        # Obtener product_id de la sesión
        product_id = request.session.get('product_id')
        logger.info(f"Product ID en sesión: {product_id}")
        
        if not product_id:
            logger.error("No se encontró product_id en sesión")
            messages.error(request, 'No se encontró el producto')
            return redirect('stock_smart:productos_lista')
            
        product = get_object_or_404(Product, id=product_id)
        logger.info(f"Producto encontrado: {product.name}")

        # Crear orden directamente
        order_number = f'ORD-{timezone.now().strftime("%Y%m%d")}-{uuid.uuid4().hex[:8]}'
        order = Order.objects.create(
            order_number=order_number,
            total_amount=product.final_price,
            status='pending',
            customer_email=request.POST.get('email', ''),
            customer_name=f"{request.POST.get('nombre', '')} {request.POST.get('apellido', '')}"
        )
        logger.info(f"Orden creada: {order.order_number}")

        # Crear item de orden
        OrderItem.objects.create(
            order=order,
            product=product,
            quantity=1,
            price=product.final_price
        )
        logger.info("Item de orden creado")

        # Datos para Flow Sandbox
        payment_data = {
            "apiKey": settings.FLOW_API_KEY,
            "commerceOrder": order.order_number,
            "subject": f"Pago Orden {order.order_number}",
            "amount": int(order.total_amount),
            "email": order.customer_email,
            "urlConfirmation": request.build_absolute_uri(reverse('stock_smart:payment_confirm')),
            "urlReturn": request.build_absolute_uri(reverse('stock_smart:payment_success')),
            "optional": {"timeout": 30}  # Timeout de 30 minutos para sandbox
        }
        
        logger.info("Datos de pago preparados")
        logger.info(json.dumps(payment_data, indent=2))
        
        # Crear firma
        params = sorted(payment_data.items())
        to_sign = ''.join(f"{key}{value}" for key, value in params)
        
        secret_key = settings.FLOW_SECRET_KEY.encode('utf-8')
        signature = hmac.new(
            secret_key,
            to_sign.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        
        payment_data['s'] = signature
        logger.info("Firma generada")
        
        # Enviar a Flow Sandbox
        response = requests.post(
            'https://sandbox.flow.cl/api/payment/create',
            data=payment_data
        )
        
        logger.info(f"Respuesta Flow Sandbox: {response.status_code}")
        logger.info(response.text)
        
        if response.status_code == 200:
            data = response.json()
            if 'url' in data and 'token' in data:
                order.flow_token = data['token']
                order.save()
                logger.info(f"Token guardado: {data['token']}")
                # Guardar order_id en sesión
                request.session['order_id'] = order.id
                return redirect(data['url'])
        
        logger.error("Error en respuesta de Flow Sandbox")
        messages.error(request, 'Error al procesar el pago')
        return redirect('stock_smart:checkout_error')
        
    except Exception as e:
        logger.error(f"Error en process_payment: {str(e)}")
        logger.error(traceback.format_exc())
        messages.error(request, 'Error al procesar el pago')
        return redirect('stock_smart:checkout_error')

def auth_page(request):
    try:
        return render(request, 'stock_smart/auth.html')
    except Exception as e:
        print(f"Error en auth_page: {str(e)}")
        return redirect('stock_smart:productos_lista')



def guest_checkout(request):
    try:
        logger.info("="*50)
        logger.info("INICIO GUEST CHECKOUT")
        
        # Obtener product_id de la sesión
        product_id = request.session.get('product_id')
        
        if not product_id:
            logger.error("No se encontró product_id en la sesión")
            messages.error(request, 'No se encontró el producto')
            return redirect('stock_smart:productos_lista')
            
        product = get_object_or_404(Product, id=product_id)
        logger.info(f"Producto encontrado: {product.name}")
        
        # Calcular precios
        base_price = product.published_price
        if product.discount_percentage > 0:
            discount_amount = (base_price * Decimal(str(product.discount_percentage))) / Decimal('100')
            final_price = base_price - discount_amount
            logger.info(f"Monto descuento: ${discount_amount}")
        else:
            final_price = base_price
            discount_amount = Decimal('0')
            
        logger.info(f"Precio final: ${final_price}")
        
        if request.method == 'POST':
            form = GuestCheckoutForm(request.POST)
            logger.info(f"Datos del formulario: {request.POST}")
            
            payment_method = request.POST.get('payment_method')
            logger.info(f"Método de pago seleccionado: {payment_method}")
            
            if form.is_valid():
                logger.info("Formulario válido - Creando orden")
                try:
                    # Generar número de orden
                    order_number = f'ORD-{timezone.now().strftime("%Y%m%d")}-{uuid.uuid4().hex[:8]}'
                    logger.info(f"Número de orden generado: {order_number}")
                    
                    # Crear orden
                    order = Order.objects.create(
                        order_number=order_number,
                        customer_name=f"{form.cleaned_data['nombre']} {form.cleaned_data['apellido']}",
                        customer_email=form.cleaned_data['email'],
                        customer_phone=form.cleaned_data['telefono'],
                        region=form.cleaned_data.get('region', ''),
                        ciudad=form.cleaned_data.get('ciudad', ''),
                        comuna=form.cleaned_data.get('comuna', ''),
                        shipping_address=form.cleaned_data.get('direccion', ''),
                        shipping_method=form.cleaned_data['shipping'],
                        payment_method=payment_method,
                        total_amount=final_price,  # Usamos el precio calculado
                        status='pending_payment'
                    )
                    logger.info(f"Orden creada con ID: {order.id}")

                    # Crear item de orden
                    OrderItem.objects.create(
                        order=order,
                        product=product,
                        quantity=1,
                        price=final_price  # Usamos el precio calculado
                    )
                    logger.info("Item de orden creado")
                    
                    # Guardar en sesión
                    request.session['order_id'] = order.id
                    logger.info(f"Order ID guardado en sesión: {order.id}")
                    
                    if payment_method == 'flow':
                        logger.info("Redirigiendo a proceso de pago Flow")
                        return redirect('stock_smart:process_payment')
                    elif payment_method == 'mercadopago':
                        logger.info("Iniciando proceso de pago con MercadoPago")
                        try:
                            mp = MercadoPagoAdapter()
                            preference = mp.create_preference(order)
                            
                            if preference:
                                logger.info(f"Preferencia MercadoPago creada: {preference['id']}")
                                return redirect(preference['init_point'])
                            else:
                                logger.error("Error al crear preferencia de MercadoPago")
                                messages.error(request, 'Error al procesar el pago con MercadoPago')
                                return redirect('stock_smart:checkout_error')
                        except Exception as e:
                            logger.error(f"Error en proceso MercadoPago: {str(e)}")
                            logger.error(traceback.format_exc())
                            messages.error(request, 'Error al procesar el pago')
                            return redirect('stock_smart:checkout_error')
                    elif payment_method == 'transfer':
                        logger.info(f"Redirigiendo a instrucciones de transferencia para orden {order.id}")
                        # Actualizar estado de la orden
                        order.status = 'pending_payment'
                        order.save()
                        logger.info(f"Estado de orden actualizado a: pending_payment")
                        return render(request, 'stock_smart/transfer_instructions.html', {
                            'order': order,
                            'bank_info': {
                                'banco': 'Banco Estado',
                                'tipo_cuenta': 'Cuenta Corriente',
                                'numero_cuenta': '123456789',
                                'rut': '12.345.678-9',
                                'nombre': 'Stock Smart SpA',
                                'email': 'pagos@stocksmart.cl'
                            }
                        })
                    
                except Exception as e:
                    logger.error(f"Error al crear la orden: {str(e)}")
                    logger.error(traceback.format_exc())
                    messages.error(request, 'Error al crear la orden')
                    return redirect('stock_smart:productos_lista')
        else:
            form = GuestCheckoutForm()
            
        context = {
            'form': form,
            'product': product,
            'base_price': base_price,
            'final_price': final_price,
            'price_without_iva': final_price / Decimal('1.19'),
            'iva': final_price - (final_price / Decimal('1.19')),
            'discount_amount': discount_amount,
            'cart_count': get_cart_count(request)
        }
        
        return render(request, 'stock_smart/guest_checkout.html', context)
        
    except Exception as e:
        logger.error("="*50)
        logger.error("ERROR EN GUEST CHECKOUT")
        logger.error(f"Error: {str(e)}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        logger.error("="*50)
        messages.error(request, 'Error al procesar el checkout')
        return redirect('stock_smart:productos_lista')





def category_detail(request, category_id):
    category = get_object_or_404(Category, id=category_id)
    products = Product.objects.filter(category=category)
    main_categories = Category.objects.filter(parent=None)
    
    context = {
        'category': category,
        'products': products,
        'main_categories': main_categories,
    }
    
    # Importante: debe renderizar categories.html
    return render(request, 'stock_smart/categories.html', context)

def product_detail(request, product_id):
    product = get_object_or_404(Product, id=product_id)
    related_products = Product.objects.filter(category=product.category).exclude(id=product.id)[:4]
    
    context = {
        'product': product,
        'related_products': related_products,
    }
    return render(request, 'stock_smart/producto_detalle.html', context)

@login_required
def profile(request):
    user = request.user
    context = {
        'user': user,
        # Puedes agregar más información del usuario aquí
        'orders': user.order_set.all() if hasattr(user, 'order_set') else [],
    }
    return render(request, 'stock_smart/profile.html', context)

@login_required
def edit_profile(request):
    if request.method == 'POST':
        form = UserProfileForm(request.POST, instance=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, 'Perfil actualizado correctamente.')
            return redirect('stock_smart:profile')
    else:
        form = UserProfileForm(instance=request.user)
    
    return render(request, 'stock_smart/edit_profile.html', {
        'form': form,
        'titulo': 'Editar Perfil'
    })

@login_required
def order_history(request):
    # Aquí irá la lógica para mostrar el historial de pedidos
    return render(request, 'stock_smart/order_history.html', {
        'titulo': 'Historial de Pedidos'
    })

@login_required
def dashboard(request):
    if not request.user.is_staff:
        messages.error(request, 'No tienes permiso para acceder al panel de administración.')
        return redirect('stock_smart:productos_lista')
    
    return render(request, 'stock_smart/dashboard/index.html', {
        'titulo': 'Panel de Administración'
    })

@login_required
def manage_products(request):
    if not request.user.is_staff:
        return redirect('stock_smart:productos_lista')
    
    products = Product.objects.all()
    return render(request, 'stock_smart/dashboard/products.html', {
        'products': products,
        'titulo': 'Gestión de Productos'
    })

@login_required
def manage_orders(request):
    if not request.user.is_staff:
        return redirect('stock_smart:productos_lista')
    
    return render(request, 'stock_smart/dashboard/orders.html', {
        'titulo': 'Gestión de Pedidos'
    })

@login_required
def manage_users(request):
    if not request.user.is_staff:
        return redirect('stock_smart:productos_lista')
    
    return render(request, 'stock_smart/dashboard/users.html', {
        'titulo': 'Gestión de Usuarios'
    })

def search_products(request):
    query = request.GET.get('q', '')
    productos = Product.objects.all()
    
    # Obtener todas las categorías activas
    categories = Category.objects.filter(is_active=True)
    
    logger.info(f"Categorías disponibles: {[cat.name for cat in categories]}")

    if query:
        productos = productos.filter(name__icontains=query) | productos.filter(description__icontains=query)
        logger.info(f"Búsqueda realizada: {query}")
        logger.info(f"Productos encontrados: {productos.count()}")

    context = {
        'productos': productos,
        'categories': categories,
        'search_query': query
    }
    return render(request, 'stock_smart/productos_lista.html', context)

def filter_products(request):
    category_id = request.GET.get('category')
    min_price = request.GET.get('min_price')
    max_price = request.GET.get('max_price')
    
    products = Product.objects.filter(active=True)
    
    if category_id:
        products = products.filter(category_id=category_id)
    if min_price:
        products = products.filter(published_price__gte=min_price)
    if max_price:
        products = products.filter(published_price__lte=max_price)
    
    return render(request, 'stock_smart/productos_lista.html', {
        'productos': products,
        'titulo': 'Productos Filtrados'
    })

def get_flow_credentials():
    """Obtener credenciales activas de Flow"""
    return FlowCredentials.objects.filter(is_active=True).first()

def flow_payment(request):
    """Iniciar el proceso de pago con Flow"""
    cart = get_or_create_cart(request)
    flow_creds = get_flow_credentials()
    
    if not flow_creds:
        messages.error(request, 'Error en la configuración de pagos.')
        return redirect('stock_smart:checkout')
    
    # Crear orden en nuestra base de datos
    order = Order.objects.create(
        user=request.user if request.user.is_authenticated else None,
        cart=cart,
        total=cart.total
    )
    
    # Datos para Flow
    payment_data = {
        "commerceOrder": str(order.id),
        "subject": "Compra en Stock Smart",
        "currency": "CLP",
        "amount": int(order.total),
        "email": request.user.email if request.user.is_authenticated else request.POST.get('email'),
        "urlConfirmation": request.build_absolute_uri(reverse('stock_smart:flow_confirm')),
        "urlReturn": request.build_absolute_uri(reverse('stock_smart:flow_success')),
    }
    
    # Llamada a la API de Flow
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {flow_creds.api_key}"
    }
    
    api_url = "https://sandbox.flow.cl/api" if flow_creds.is_sandbox else "https://www.flow.cl/api"
    
    response = requests.post(
        f"{api_url}/payment/create",
        json=payment_data,
        headers=headers
    )
    
    if response.status_code == 200:
        flow_data = response.json()
        order.flow_token = flow_data['token']
        order.save()
        return redirect(flow_data['url'] + "?token=" + flow_data['token'])
    else:
        messages.error(request, 'Error al procesar el pago. Por favor, intente nuevamente.')
        return redirect('stock_smart:checkout')

@csrf_exempt
def flow_confirm(request):
    """Confirmación de pago desde Flow"""
    if request.method == "POST":
        token = request.POST.get('token')
        flow_creds = get_flow_credentials()
        
        if not flow_creds:
            return HttpResponse(status=500)
        
        # Verificar el pago con Flow
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {flow_creds.api_key}"
        }
        
        api_url = "https://sandbox.flow.cl/api" if flow_creds.is_sandbox else "https://www.flow.cl/api"
        
        response = requests.get(
            f"{api_url}/payment/getStatus",
            params={"token": token},
            headers=headers
        )
        
        if response.status_code == 200:
            payment_data = response.json()
            order = Order.objects.get(id=payment_data['commerceOrder'])
            
            if payment_data['status'] == 2:  # Pago exitoso
                order.status = 'PAID'
                order.save()
                
                # Actualizar stock
                cart = order.cart
                for item in cart.cartitem_set.all():
                    product = item.product
                    product.stock -= item.quantity
                    product.save()
                
                cart.completed = True
                cart.save()
                
            return HttpResponse(status=200)
    
    return HttpResponse(status=400)

def flow_success(request):
    """Página de éxito después del pago"""
    token = request.GET.get('token')
    try:
        order = Order.objects.get(flow_token=token)
        messages.success(request, '¡Pago realizado con éxito! Gracias por tu compra.')
        return render(request, 'stock_smart/flow_success.html', {
            'order': order,
            'titulo': 'Pago Exitoso'
        })
    except Order.DoesNotExist:
        messages.error(request, 'Orden no encontrada.')
        return redirect('stock_smart:productos_lista')

def flow_failure(request):
    """Página de fallo de pago"""
    messages.error(request, 'El pago no pudo ser procesado. Por favor, intente nuevamente.')
    return render(request, 'stock_smart/flow_failure.html', {
        'titulo': 'Error en el Pago'
    })

def about(request):
    """Vista para la página Acerca de"""
    return render(request, 'stock_smart/about.html', {
        'titulo': 'Acerca de Nosotros'
    })

def contacto(request):
    """Vista para la página de contacto"""
    if request.method == 'POST':
        # Aquí puedes agregar la lógica para procesar el formulario
        messages.success(request, 'Mensaje enviado correctamente. Nos pondremos en contacto contigo pronto.')
        return redirect('stock_smart:contacto')
        
    return render(request, 'stock_smart/contacto.html', {
        'titulo': 'Contacto'
    })

def terminos(request):
    """Vista para la página de términos y condiciones"""
    return render(request, 'stock_smart/terminos.html', {
        'titulo': 'Términos y Condiciones'
    })


def update_cart_item(request, item_id):
    """
    Vista para actualizar la cantidad de un item en el carrito
    """
    if request.method == 'POST':
        try:
            cart_item = get_object_or_404(CartItem, id=item_id)
            quantity = int(request.POST.get('quantity', 1))
            
            if quantity > 0:
                cart_item.quantity = quantity
                cart_item.save()
                return JsonResponse({
                    'success': True,
                    'message': 'Cantidad actualizada',
                    'new_quantity': quantity,
                    'new_total': cart_item.total
                })
            else:
                cart_item.delete()
                return JsonResponse({
                    'success': True,
                    'message': 'Item eliminado del carrito'
                })
                
        except (ValueError, TypeError):
            return JsonResponse({
                'success': False,
                'error': 'Cantidad inválida'
            }, status=400)
            
    return JsonResponse({
        'success': False,
        'error': 'Método no permitido'
    }, status=405)

@login_required
def cart_checkout(request):
    """
    Vista para el proceso de checkout del carrito completo
    """
    try:
        # Obtener el carrito activo del usuario
        cart = Cart.objects.get(
            user=request.user,
            is_active=True
        )
        
        # Verificar que haya items en el carrito
        if not cart.cartitem_set.exists():
            messages.warning(request, 'Tu carrito está vacío')
            return redirect('stock_smart:cart')
        
        # Calcular totales
        subtotal = sum(item.total for item in cart.cartitem_set.all())
        iva = subtotal * 0.19
        total = subtotal + iva
        
        context = {
            'cart': cart,
            'cart_items': cart.cartitem_set.all(),
            'subtotal': subtotal,
            'iva': iva,
            'total': total,
        }
        
        return render(request, 'stock_smart/cart_checkout.html', context)
        
    except Cart.DoesNotExist:
        messages.error(request, 'No se encontró un carrito activo')
        return redirect('stock_smart:productos_lista')

def generate_order_number():
    """Genera un número de orden único"""
    return f"ORD-{uuid.uuid4().hex[:8].upper()}"

def cart_payment(request):
    """Vista común para proceso de pago (registrado y guest)"""
    # Obtener datos de la sesión
    checkout_data = request.session.get('checkout_data', {})
    
    if not checkout_data:
        messages.error(request, 'No hay información de checkout')
        return redirect('stock_smart:productos_lista')
    
    # Si el usuario est autenticado, prellenar datos
    if request.user.is_authenticated:
        context = {
            'user_data': {
                'email': request.user.email,
                'first_name': request.user.first_name,
                'last_name': request.user.last_name,
                'phone': request.user.profile.phone,
                'address': request.user.profile.address,
                'city': request.user.profile.city,
                'region': request.user.profile.region,
            }
        }
    else:
        context = {}
    
    # Agregar datos del checkout
    context.update(checkout_data)
    
    return render(request, 'stock_smart/payment.html', context)

def cart_confirm(request):
    """
    Vista para confirmar el pedido después del pago
    """
    # Obtener el número de orden de la sesión
    order_number = request.session.get('order_number')
    
    if not order_number:
        messages.error(request, 'No se encontró información del pedido')
        return redirect('stock_smart:productos_lista')
    
    try:
        # Obtener la orden
        order = Order.objects.get(order_number=order_number)
        
        # Limpiar la sesión
        if 'order_number' in request.session:
            del request.session['order_number']
        if 'checkout_data' in request.session:
            del request.session['checkout_data']
            
        context = {
            'order': order,
            'payment_method': order.get_payment_method_display(),
            'shipping_method': order.get_shipping_method_display(),
        }
        
        return render(request, 'stock_smart/order_confirmation.html', context)
        
    except Order.DoesNotExist:
        messages.error(request, 'No se encontró la orden especificada')
        return redirect('stock_smart:productos_lista')

def buy_now(request, product_id):
    """
    Vista para compra directa de un producto
    """
    try:
        product = get_object_or_404(Product, id=product_id)
        
        if product.stock <= 0:
            messages.error(request, 'Lo sentimos, este producto está agotado.')
            return redirect('stock_smart:productos_lista')
        
        # El precio ya incluye IVA
        total = product.final_price
        
        # Guardar información en la sesión
        request.session['buy_now_data'] = {
            'product_id': product_id,
            'product_name': product.name,
            'product_price': float(product.final_price),
            'quantity': 1,
            'total': float(total),
            'timestamp': str(timezone.now())
        }
        
        # Asegúrate de guardar el product_id en la sesión
        request.session['product_id'] = product_id
        
        context = {
            'product': product,
            'total': total,
            'is_buy_now': True
        }
        
        return render(request, 'stock_smart/checkout_options.html', context)
        
    except Product.DoesNotExist:
        messages.error(request, 'El producto no existe.')
        return redirect('stock_smart:productos_lista')
    except Exception as e:
        logger.error(f"Error en buy_now: {str(e)}")
        messages.error(request, f'Ocurrió un error al procesar la compra: {str(e)}')
        return redirect('stock_smart:productos_lista')

def buy_now_payment(request, product_id):
    """
    Procesa el pago de compra directa mediante Flow
    """
    try:
        # Obtener datos de la sesión
        buy_data = request.session.get('buy_now_data')
        if not buy_data:
            raise ValueError("No hay datos de compra en la sesión")

        # Crear orden en nuestro sistema
        order = Order.objects.create(
            order_number=generate_order_number(),
            user=request.user if request.user.is_authenticated else None,
            total_amount=buy_data['total'],
            payment_method='FLOW',
            status='PENDING'
        )

        # Preparar datos para Flow
        commerceOrder = order.order_number
        subject = f"Pago Stock Smart - Orden {commerceOrder}"
        amount = int(float(buy_data['total']))
        email = request.user.email if request.user.is_authenticated else request.POST.get('email')
        
        # URLs de respuesta
        urlConfirmation = request.build_absolute_uri(reverse('stock_smart:flow_confirm'))
        urlReturn = request.build_absolute_uri(reverse('stock_smart:flow_return'))

        # Datos para Flow
        payment_data = {
            "commerceOrder": commerceOrder,
            "subject": subject,
            "currency": "CLP",
            "amount": amount,
            "email": email,
            "urlConfirmation": urlConfirmation,
            "urlReturn": urlReturn,
            "optional": json.dumps({
                "order_type": "buy_now",
                "product_id": product_id
            })
        }

        # Firmar datos
        sign = create_flow_signature(payment_data)
        payment_data["s"] = sign

        # Enviar a Flow
        flow_response = requests.post(
            f"{settings.FLOW_API_URL}/payment/create",
            json=payment_data,
            headers={"Content-Type": "application/json"}
        )

        if flow_response.status_code == 200:
            flow_data = flow_response.json()
            if flow_data.get("url"):
                return redirect(flow_data["url"])
            else:
                raise ValueError("No se recibió URL de pago de Flow")
        else:
            raise ValueError(f"Error en Flow: {flow_response.text}")

    except Exception as e:
        messages.error(request, f"Error al procesar el pago: {str(e)}")
        return redirect('stock_smart:checkout_options')

def cart_payment(request):
    """
    Procesa el pago del carrito mediante Flow
    """
    try:
        cart = Cart.get_active_cart(request)
        if not cart or not cart.cartitem_set.exists():
            raise ValueError("Carrito vacío")

        # Crear orden
        order = Order.objects.create(
            order_number=generate_order_number(),
            user=request.user if request.user.is_authenticated else None,
            total_amount=cart.total,
            payment_method='FLOW',
            status='PENDING'
        )

        # Preparar datos para Flow
        commerceOrder = order.order_number
        subject = f"Pago Stock Smart - Orden {commerceOrder}"
        amount = int(float(cart.total))
        email = request.user.email if request.user.is_authenticated else request.POST.get('email')

        # URLs de respuesta
        urlConfirmation = request.build_absolute_uri(reverse('stock_smart:flow_confirm'))
        urlReturn = request.build_absolute_uri(reverse('stock_smart:flow_return'))

        # Datos para Flow
        payment_data = {
            "commerceOrder": commerceOrder,
            "subject": subject,
            "currency": "CLP",
            "amount": amount,
            "email": email,
            "urlConfirmation": urlConfirmation,
            "urlReturn": urlReturn,
            "optional": json.dumps({
                "order_type": "cart",
                "cart_id": cart.id
            })
        }

        # Firmar datos
        sign = create_flow_signature(payment_data)
        payment_data["s"] = sign

        # Enviar a Flow
        flow_response = requests.post(
            f"{settings.FLOW_API_URL}/payment/create",
            json=payment_data,
            headers={"Content-Type": "application/json"}
        )

        if flow_response.status_code == 200:
            flow_data = flow_response.json()
            if flow_data.get("url"):
                return redirect(flow_data["url"])
            else:
                raise ValueError("No se recibió URL de pago de Flow")
        else:
            raise ValueError(f"Error en Flow: {flow_response.text}")

    except Exception as e:
        messages.error(request, f"Error al procesar el pago: {str(e)}")
        return redirect('stock_smart:cart')

def create_flow_signature(data):
    """
    Crea la firma para Flow
    """
    # Ordenar keys alfabéticamente
    sorted_data = dict(sorted(data.items()))
    
    # Concatenar valores
    values_string = ''.join(str(value) for value in sorted_data.values())
    
    # Crear firma
    secret_key = settings.FLOW_SECRET_KEY.encode('utf-8')
    signature = hmac.new(secret_key, 
                        values_string.encode('utf-8'), 
                        hashlib.sha256).hexdigest()
    
    return signature

def flow_return(request):
    """
    Vista de retorno después del pago en Flow
    """
    try:
        token = request.GET.get('token')
        if not token:
            token = request.POST.get('token')
        
        # Verificar el estado del pago
        params = {
            'apiKey': settings.FLOW_API_KEY,
            'token': token
        }
        params['s'] = generate_signature(params)
        
        response = requests.get(
            'https://sandbox.flow.cl/api/payment/getStatus',
            params=params
        )
        
        if response.status_code == 200:
            data = response.json()
            try:
                order = Order.objects.get(flow_token=token)
                
                if data['status'] == 2:  # Pago exitoso
                    order.status = 'PAID'
                    order.save()
                    
                    # Actualizar stock
                    for item in order.orderitem_set.all():
                        product = item.product
                        product.stock -= item.quantity
                        product.save()
                    
                    # Limpiar carrito
                    if 'cart_id' in request.session:
                        del request.session['cart_id']
                    
                    messages.success(request, '¡Pago realizado con éxito!')
                    return render(request, 'stock_smart/payment_success.html', {
                        'order': order
                    })
                else:
                    order.status = 'FAILED'
                    order.save()
                    messages.error(request, 'El pago no pudo ser procesado')
                    return render(request, 'stock_smart/payment_failed.html', {
                        'order': order
                    })
                    
            except Order.DoesNotExist:
                messages.error(request, 'Orden no encontrada')
                return redirect('stock_smart:guest_checkout')
                
        else:
            raise ValueError(f"Error en la respuesta de Flow: {response.text}")
            
    except Exception as e:
        logger.error(f"Error en flow_return: {str(e)}")
        messages.error(request, 'Error al procesar el pago')
        return redirect('stock_smart:guest_checkout')

@csrf_exempt
def flow_confirm(request):
    """Webhook para confirmación de Flow"""
    try:
        token = request.POST.get('token')
        
        # Verificar el pago
        params = {
            'apiKey': settings.FLOW_API_KEY,
            'token': token
        }
        params['s'] = generate_signature(params)
        
        response = requests.get(
            'https://sandbox.flow.cl/api/payment/getStatus',
            params=params
        )
        
        if response.status_code == 200:
            data = response.json()
            try:
                order = Order.objects.get(flow_token=token)
                order.status = 'PAID' if data['status'] == 2 else 'FAILED'
                order.save()
                
                return HttpResponse(status=200)
            except Order.DoesNotExist:
                return HttpResponse(status=404)
        else:
            return HttpResponse(status=400)
            
    except Exception as e:
        logger.error(f"Error en flow_confirm: {str(e)}")
        return HttpResponse(status=500)
    return HttpResponse(status=405)

def buy_now_confirm(request, product_id):
    """
    Vista para confirmar la compra rápida de un producto
    """
    try:
        product = get_object_or_404(Product, id=product_id)
        
        # Verificar stock
        if product.stock <= 0:
            messages.error(request, 'Lo sentimos, este producto está agotado.')
            return redirect('stock_smart:productos_lista')
        
        # Calcular total
        total = product.final_price
        
        # Guardar información en la sesión
        request.session['buy_now_data'] = {
            'product_id': product_id,
            'total': float(total),
            'is_buy_now': True
        }
        
        # Redirigir al checkout
        return redirect('stock_smart:guest_checkout')
        
    except Exception as e:
        logger.error(f"Error en buy_now_confirm: {str(e)}")
        messages.error(request, 'Error al procesar la compra rápida. Por favor, intente nuevamente.')
        return redirect('stock_smart:productos_lista')

@require_http_methods(["POST"])
def update_cart_api(request):
    """
    API endpoint para actualizar el carrito de forma asíncrona
    """
    try:
        data = json.loads(request.body)
        action = data.get('action')
        product_id = data.get('product_id')
        quantity = int(data.get('quantity', 1))

        # Obtener o crear carrito
        cart = Cart.get_active_cart(request)
        product = get_object_or_404(Product, id=product_id)

        if action == 'add':
            # Agregar o actualizar item
            cart_item, created = CartItem.objects.get_or_create(
                cart=cart,
                product=product,
                defaults={'quantity': quantity}
            )
            
            if not created:
                cart_item.quantity += quantity
                cart_item.save()

        elif action == 'update':
            # Actualizar cantidad
            cart_item = get_object_or_404(CartItem, cart=cart, product=product)
            if quantity > 0:
                cart_item.quantity = quantity
                cart_item.save()
            else:
                cart_item.delete()

        elif action == 'remove':
            # Eliminar item
            CartItem.objects.filter(cart=cart, product=product).delete()

        # Calcular totales
        cart_total = sum(item.total for item in cart.cartitem_set.all())
        cart_count = cart.cartitem_set.count()

        return JsonResponse({
            'success': True,
            'cart_total': float(cart_total),
            'cart_count': cart_count,
            'message': 'Carrito actualizado exitosamente'
        })

    except Product.DoesNotExist:
        return JsonResponse({
            'success': False,
            'error': 'Producto no encontrado'
        }, status=404)
    except (ValueError, TypeError) as e:
        logger.exception(f"Error de valor en la actualización del carrito: {str(e)}")
        return JsonResponse({
            'success': False,
            'error': 'Cantidad inválida'
        }, status=400)
    except Exception as e:
        logger.exception(f"Error inesperado en la actualización del carrito: {str(e)}")
        return JsonResponse({
            'success': False,
            'error': 'Error al actualizar el carrito'
        }, status=500)

    """Genera un número de orden único"""
    return f"ORD-{uuid.uuid4().hex[:8].upper()}"

def process_guest_order(request):
    """
    Procesa la orden de un invitado y redirige al pago
    """
    if request.method == 'POST':
        try:
            # Obtener datos de la sesión
            checkout_data = request.session.get('checkout_data', {})
            if not checkout_data:
                raise ValueError("No hay datos de checkout")

            # Crear la orden
            order = Order.objects.create(
                order_number=generate_order_number(),
                first_name=request.POST.get('first_name'),
                last_name=request.POST.get('last_name'),
                email=request.POST.get('email'),
                phone=request.POST.get('phone'),
                total_amount=checkout_data.get('total'),
                status='PENDING'
            )

            # Crear items de la orden
            if checkout_data.get('is_buy_now'):
                product = Product.objects.get(id=checkout_data['product_id'])
                OrderItem.objects.create(
                    order=order,
                    product=product,
                    quantity=1,
                    price=product.final_price
                )
            else:
                cart = Cart.objects.get(id=checkout_data['cart_id'])
                for item in cart.cartitem_set.all():
                    OrderItem.objects.create(
                        order=order,
                        product=item.product,
                        quantity=item.quantity,
                        price=item.product.final_price
                    )

            # Preparar datos para Flow
            flow_data = {
                'commerceOrder': order.order_number,
                'subject': f'Orden #{order.order_number}',
                'currency': 'CLP',
                'amount': int(float(order.total_amount)),
                'email': order.email,
                'urlConfirmation': request.build_absolute_uri(reverse('stock_smart:flow_confirm')),
                'urlReturn': request.build_absolute_uri(reverse('stock_smart:flow_return')),
                'apiKey': settings.FLOW_API_KEY
            }

            # Ordenar y firmar
            sorted_params = dict(sorted(flow_data.items()))
            sign_string = ''
            for key, value in sorted_params.items():
                sign_string += str(value)

            # Generar firma
            secret_key = settings.FLOW_SECRET_KEY.encode('utf-8')
            signature = hmac.new(
                secret_key,
                sign_string.encode('utf-8'),
                hashlib.sha256
            ).hexdigest()

            # Agregar firma a los datos
            flow_data['s'] = signature

            # Llamada a Flow
            response = requests.post(
                'https://sandbox.flow.cl/api/payment/create',
                json=flow_data,
                headers={'Content-Type': 'application/json'}
            )

            if response.status_code == 200:
                flow_response = response.json()
                order.flow_token = flow_response.get('token')
                order.save()
                
                # Redirigir a Flow
                return redirect(f"https://sandbox.flow.cl/app/web/pay.php?token={flow_response['token']}")
            else:
                logger.error(f"Error de Flow: {response.text}")
                raise ValueError(f"Error al crear pago en Flow: {response.text}")

        except Product.DoesNotExist:
            messages.error(request, 'Producto no encontrado')
            return redirect('stock_smart:productos_lista')
        except Exception as e:
            logger.error(f"Error en process_guest_order: {str(e)}")
            messages.error(request, f'Error al procesar la orden: {str(e)}')
            return redirect('stock_smart:productos_lista')

    return redirect('stock_smart:productos_lista')

def transfer_instructions(request, order_id):
    try:
        logger.info(f"Mostrando instrucciones de transferencia para orden {order_id}")
        order = get_object_or_404(Order, id=order_id)
        
        context = {
            'order': order,
            'bank_info': {
                'banco': 'Banco Estado',
                'tipo_cuenta': 'Cuenta Corriente',
                'numero_cuenta': '123456789',
                'rut': '12.345.678-9',
                'nombre': 'Stock Smart SpA',
                'email': 'pagos@stocksmart.cl'
            }
        }
        
        return render(request, 'stock_smart/transfer_instructions.html', context)
        
    except Exception as e:
        logger.error(f"Error al mostrar instrucciones de transferencia: {str(e)}")
        messages.error(request, 'Error al mostrar las instrucciones de transferencia')
        return redirect('stock_smart:productos_lista')

@csrf_exempt
def flow_confirmation(request):
    """Endpoint que recibe la confirmación de Flow"""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            order_id = data.get('commerceOrder')
            flow_status = data.get('status')
            
            # Actualizar el estado de la orden según la respuesta de Flow
            order = Order.objects.get(id=order_id)
            if flow_status == 'READY':  # Pago exitoso
                order.status = 'paid'
                order.save()
                return HttpResponse(status=200)
            else:
                order.status = 'failed'
                order.save()
                return HttpResponse(status=200)
                
        except Exception as e:
            logger.error(f"Error en flow_confirmation: {str(e)}")
            return HttpResponse(status=500)
    return HttpResponse(status=405)

def flow_return(request):
    """Vista que maneja el retorno del usuario desde Flow"""
    try:
        token = request.GET.get('token')
        if not token:
            token = request.POST.get('token')
        
        # Verificar el estado del pago
        params = {
            'apiKey': settings.FLOW_API_KEY,
            'token': token
        }
        params['s'] = generate_signature(params)
        
        response = requests.get(
            'https://sandbox.flow.cl/api/payment/getStatus',
            params=params
        )
        
        if response.status_code == 200:
            data = response.json()
            try:
                order = Order.objects.get(flow_token=token)
                
                if data['status'] == 2:  # Pago exitoso
                    order.status = 'PAID'
                    order.save()
                    
                    # Actualizar stock
                    for item in order.orderitem_set.all():
                        product = item.product
                        product.stock -= item.quantity
                        product.save()
                    
                    # Limpiar carrito
                    if 'cart_id' in request.session:
                        del request.session['cart_id']
                    
                    messages.success(request, '¡Pago realizado con éxito!')
                    return render(request, 'stock_smart/payment_success.html', {
                        'order': order
                    })
                else:
                    order.status = 'FAILED'
                    order.save()
                    messages.error(request, 'El pago no pudo ser procesado')
                    return render(request, 'stock_smart/payment_failed.html', {
                        'order': order
                    })
                    
            except Order.DoesNotExist:
                messages.error(request, 'Orden no encontrada')
                return redirect('stock_smart:guest_checkout')
                
        else:
            raise ValueError(f"Error en la respuesta de Flow: {response.text}")
            
    except Exception as e:
        logger.error(f"Error en flow_return: {str(e)}")
        messages.error(request, 'Error al procesar el pago')
        return redirect('stock_smart:guest_checkout')

def process_flow_payment(request):
    """
    Procesa el pago con Flow en modo sandbox
    """
    try:
        logger.info("Iniciando proceso de pago con Flow")
        
        # Obtener datos del checkout
        checkout_data = request.session.get('checkout_data', {})
        if not checkout_data:
            raise ValueError("No hay datos de checkout disponibles")

        # Convertir el total a un entero sin decimales
        total = checkout_data.get('total', 0)
        if isinstance(total, str):
            total = total.replace(',', '').replace('.', '')
        else:
            total = int(float(total))
        
        logger.info(f"Total formateado para Flow: {total}")

        # Generar número de orden único
        order_number = str(uuid.uuid4())[:20]
        
        # Preparar datos para Flow
        payment_data = {
            'apiKey': settings.FLOW_API_KEY,
            'commerceOrder': order_number,
            'subject': f'Compra Stock Smart #{order_number}',
            'currency': 'CLP',
            'amount': total,  # Ahora es un entero limpio
            'email': request.POST.get('email'),
            'urlConfirmation': request.build_absolute_uri(reverse('stock_smart:flow_confirm')),
            'urlReturn': request.build_absolute_uri(reverse('stock_smart:flow_return')),
        }

        logger.info(f"Datos de pago preparados: {payment_data}")
        
        # Ordenar parámetros alfabéticamente
        sorted_params = dict(sorted(payment_data.items()))
        
        # Crear string para firma
        sign_string = ''
        for key, value in sorted_params.items():
            sign_string += str(value)

        # Generar firma
        secret_key = settings.FLOW_SECRET_KEY.encode('utf-8')
        signature = hmac.new(
            secret_key,
            sign_string.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

        # Agregar firma a los datos
        payment_data['s'] = signature

        logger.info("Enviando solicitud a Flow")
        
        # Hacer petición a Flow
        response = requests.post(
            'https://sandbox.flow.cl/api/payment/create',
            json=payment_data,
            headers={'Content-Type': 'application/json'}
        )

        logger.info(f"Respuesta de Flow: {response.status_code} - {response.text}")

        if response.status_code == 200:
            flow_response = response.json()
            
            # Guardar información del pago en la sesión
            request.session['flow_payment'] = {
                'token': flow_response['token'],
                'order_number': order_number
            }
            
            # Crear orden en la base de datos
            order = Order.objects.create(
                order_number=order_number,
                first_name=request.POST.get('first_name'),
                last_name=request.POST.get('last_name'),
                email=request.POST.get('email'),
                phone=request.POST.get('phone'),
                total_amount=Decimal(str(checkout_data.get('total', 0))),
                flow_token=flow_response['token'],
                status='PENDING'
            )

            # Guardar items de la orden
            if checkout_data.get('is_buy_now'):
                product = Product.objects.get(id=checkout_data['product_id'])
                OrderItem.objects.create(
                    order=order,
                    product=product,
                    quantity=1,
                    price=product.final_price
                )
            else:
                cart = Cart.get_active_cart(request)
                for item in cart.cartitem_set.all():
                    OrderItem.objects.create(
                        order=order,
                        product=item.product,
                        quantity=item.quantity,
                        price=item.product.final_price
                    )

            # Redirigir a la página de pago de Flow
            payment_url = f"{flow_response['url']}?token={flow_response['token']}"
            logger.info(f"Redirigiendo a Flow: {payment_url}")
            return redirect(payment_url)

        else:
            raise ValueError(f"Error en la respuesta de Flow: {response.text}")

    except Exception as e:
        logger.error(f"Error en process_flow_payment: {str(e)}")
        messages.error(request, 'Error al procesar el pago. Por favor, intente nuevamente.')
        return redirect('stock_smart:guest_checkout')

@csrf_exempt
def payment_notify(request):
    """Webhook para notificaciones de Flow"""
    Payment = get_payment_model()
    try:
        payment_id = request.POST.get('payment_id')
        payment = Payment.objects.get(id=payment_id)
        payment.status = PaymentStatus.CONFIRMED
        payment.save()
        return HttpResponse(status=200)
    except Exception as e:
        logger.error(f"Error en payment_notify: {str(e)}")
        return HttpResponse(status=500)

@method_decorator(csrf_exempt, name='dispatch')
class PaymentSuccessView(View):
    def post(self, request, *args, **kwargs):
        logger.info("="*50)
        logger.info("RECIBIENDO POST DE FLOW")
        logger.info(f"POST Data: {request.POST}")
        
        token = request.POST.get('token')
        payment_status = request.POST.get('status')
        
        logger.info(f"Token: {token}")
        logger.info(f"Estado del pago: {payment_status}")

        if not token:
            logger.error("No se recibi token")
            return redirect('stock_smart:productos_lista')

        try:
            order = Order.objects.get(flow_token=token)
            
            if payment_status == '2':  # Pago exitoso
                order.status = 'PAID'
                order.payment_date = timezone.now()
                order.save()
                logger.info(f"Orden {order.order_number} marcada como pagada")
                
                return render(request, 'stock_smart/payment_success.html', {
                    'order': order,
                    'order_number': order.order_number,
                    'customer_email': order.customer_email
                })
            
            # Si el pago fue rechazado
            logger.warning(f"Pago rechazado o con error. Estado: {payment_status}")
            order.status = 'REJECTED'
            order.save()
            
            return render(request, 'stock_smart/payment_rejected.html', {
                'order': order,
                'order_number': order.order_number
            })
            
        except Order.DoesNotExist:
            logger.error(f"No se encontró orden para el token: {token}")
            messages.error(request, 'Orden no encontrada')
            return redirect('stock_smart:productos_lista')
        except Exception as e:
            logger.error(f"Error procesando pago: {str(e)}")
            messages.error(request, 'Error procesando el pago')
            return redirect('stock_smart:productos_lista')

    def get(self, request, *args, **kwargs):
        messages.warning(request, 'Acceso no válido')
        return redirect('stock_smart:productos_lista')

def send_confirmation_email(order):
    """Función auxiliar para enviar correo de confirmación"""
    try:
        subject = f'Confirmación de Pago - Orden #{order.order_number}'
        message = f"""
        ¡Gracias por tu compra!
        
        Detalles de la orden:
        Número de orden: {order.order_number}
        Total: ${order.total_amount}
        Estado: Pagado
        
        Pronto recibirás información sobre el envío.
        """
        
        send_mail(
            subject,
            message,
            'noreply@tusitio.com',
            [order.customer_email],
            fail_silently=False,
        )
    except Exception as e:
        logger.error(f"Error al enviar correo de confirmación: {str(e)}")
        # No relanzo la excepción para no interrumpir el flujo principal

def payment_cancel(request):
    try:
        messages.warning(request, 'El pago ha sido cancelado')
        return redirect('stock_smart:productos_lista')
    except Exception as e:
        print(f"Error en payment_cancel: {str(e)}")
        return redirect('stock_smart:productos_lista')

def generate_signature(params):
    """Genera la firma HMAC para Flow"""
    sorted_params = ''.join(f"{key}{value}" for key, value in sorted(params.items()))
    signature = hmac.new(
        settings.FLOW_SECRET_KEY.encode('utf-8'), 
        sorted_params.encode('utf-8'), 
        hashlib.sha256
    ).hexdigest()
    return signature

def get_or_create_cart(request):
    if request.user.is_authenticated:
        cart, created = Cart.objects.get_or_create(
            user=request.user,
            completed=False
        )
    else:
        cart_id = request.session.get('cart_id')
        if cart_id:
            cart = Cart.objects.filter(id=cart_id, completed=False).first()
            if not cart:
                cart = Cart.objects.create()
                request.session['cart_id'] = cart.id
        else:
            cart = Cart.objects.create()
            request.session['cart_id'] = cart.id
    return cart

def cart_view(request):
    cart_items = []
    total_amount = Decimal('0')
    total_discount = Decimal('0')
    
    try:
        cart = request.session.get('cart', {})
        logger.info(f"Carrito actual: {cart}")
        
        # Procesar cada item en el carrito
        for product_id, item in cart.items():
            try:
                product = Product.objects.get(id=product_id)
                quantity = Decimal(str(item.get('quantity', 0)))
                price = Decimal(str(item.get('price', '0')))
                
                item_total = price * quantity
                total_amount += item_total
                
                cart_items.append({
                    'product': product,
                    'quantity': quantity,
                    'price': price,
                    'total': item_total
                })
                
                logger.info(f"Producto procesado: {product.name}, Precio: {price}, Cantidad: {quantity}, Total: {item_total}")
                
            except Product.DoesNotExist:
                logger.error(f"Producto no encontrado: {product_id}")
                continue
            except Exception as e:
                logger.error(f"Error procesando producto {product_id}: {str(e)}")
                continue
        
        logger.info(f"Total amount final: {total_amount}, Items procesados: {len(cart_items)}")
        
        context = {
            'cart_items': cart_items,
            'total_amount': total_amount,
            'total_discount': total_discount,
            'subtotal': total_amount,
            'iva': total_amount * Decimal('0.19'),
            'cart_count': len(cart_items)
        }
        
        return render(request, 'stock_smart/cart.html', context)
        
    except Exception as e:
        logger.error(f"Error general en cart_view: {str(e)}")
        return render(request, 'stock_smart/cart.html', {
            'error': 'Error al cargar el carrito',
            'cart_items': []
        })

def update_cart(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            product_id = str(data.get('product_id'))
            action = data.get('action')
            
            logger.info(f"Actualizando carrito - ID: {product_id}, Acción: {action}")
            
            cart = request.session.get('cart', {})
            
            if not cart:
                logger.error("Carrito vacío")
                return JsonResponse({
                    'success': False,
                    'error': 'El carrito está vacío'
                })
            
            if product_id not in cart:
                logger.error(f"Producto {product_id} no encontrado en el carrito")
                return JsonResponse({
                    'success': False,
                    'error': 'Producto no encontrado en el carrito'
                })
            
            if action == 'add':
                cart[product_id]['quantity'] += 1
                logger.info(f"Cantidad incrementada para producto {product_id}")
            elif action == 'subtract':
                if cart[product_id]['quantity'] > 1:
                    cart[product_id]['quantity'] -= 1
                    logger.info(f"Cantidad reducida para producto {product_id}")
                else:
                    logger.info(f"No se puede reducir más la cantidad del producto {product_id}")
            elif action == 'remove':
                del cart[product_id]
                logger.info(f"Producto {product_id} eliminado del carrito")
            
            request.session['cart'] = cart
            request.session.modified = True
            
            cart_count = sum(item['quantity'] for item in cart.values())
            
            return JsonResponse({
                'success': True,
                'cart_count': cart_count,
                'message': f'Carrito actualizado correctamente. Acción: {action}'
            })
            
        except json.JSONDecodeError:
            logger.error("Error al decodificar JSON")
            return JsonResponse({
                'success': False,
                'error': 'Error en el formato de la solicitud'
            })
        except Exception as e:
            logger.error(f"Error inesperado: {str(e)}")
            return JsonResponse({
                'success': False,
                'error': str(e)
            })
    return JsonResponse({
        'success': False,
        'error': 'Método no permitido'
    })

def remove_from_cart(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            product_id = str(data.get('product_id'))
            
            # Eliminar del carrito
            cart = request.session.get('cart', {})
            if product_id in cart:
                del cart[product_id]
                request.session['cart'] = cart
                request.session.modified = True
                
                # Calcular nuevo total
                cart_total = sum(float(item['price']) * item['quantity'] for item in cart.values())
                cart_count = sum(item['quantity'] for item in cart.values())
                
                return JsonResponse({
                    'success': True,
                    'cart_total': f"{cart_total:,.0f}",
                    'cart_count': cart_count
                })
            
            return JsonResponse({
                'success': False,
                'error': 'Producto no encontrado en el carrito'
            })
            
        except Exception as e:
            print(f"Error en remove_from_cart: {str(e)}")
            return JsonResponse({
                'success': False,
                'error': str(e)
            })
    
    return JsonResponse({'success': False})

def category_products(request, category_id):
    category = get_object_or_404(Category, id=category_id)
    
    # Obtener productos de la categoría actual y sus subcategorías
    categories = [category]
    if category.children.exists():
        categories.extend(category.children.all())
        for child in category.children.all():
            if child.children.exists():
                categories.extend(child.children.all())
    
    products = Product.objects.filter(
        category__in=categories,
        active=True
    ).distinct()
    
    context = {
        'category': category,
        'products': products,
        'main_categories': Category.objects.filter(parent=None, is_active=True)
    }
    return render(request, 'stock_smart/category_products.html', context)

def view_cart(request):
    # Obtener carrito del visitante
    cart = Cart.get_cart_for_visitor(request.visitor_id)
    cart_items = CartItem.objects.filter(cart=cart)
    
    context = {
        'cart_items': cart_items,
        'cart_total': sum(item.subtotal for item in cart_items),
        'main_categories': Category.objects.filter(parent=None, is_active=True)
    }
    return render(request, 'stock_smart/cart.html', context)

def productos_lista(request):
    try:
        search_query = request.GET.get('q', '')
        productos = Product.objects.all()
        
        # Obtener todas las categorías activas, ordenadas por nombre
        categories = Category.objects.filter(is_active=True).order_by('name')
        
        logger.info(f"Categorías cargadas: {[cat.name for cat in categories]}")

        if search_query:
            productos = productos.filter(name__icontains=search_query) | productos.filter(description__icontains=search_query)
            logger.info(f"Búsqueda realizada: {search_query}")
            logger.info(f"Productos encontrados: {productos.count()}")

        context = {
            'productos': productos,
            'categories': categories,
            'search_query': search_query
        }
        return render(request, 'stock_smart/productos_lista.html', context)
    except Exception as e:
        logger.error(f"Error al cargar categorías: {str(e)}")
        return render(request, 'stock_smart/productos_lista.html', {
            'productos': Product.objects.all(),
            'categories': [],
            'search_query': search_query if 'search_query' in locals() else ''
        })

def productos_por_categoria(request, slug):
    try:
        logger.info(f"Buscando productos para categoría: {slug}")
        
        # Obtener la categoría actual
        categoria = get_object_or_404(Category, slug=slug)
        logger.info(f"Categoría encontrada: {categoria.name}, ID: {categoria.id}")
        
        # Obtener todas las categorías activas para el menú
        categories = Category.objects.filter(is_active=True).order_by('name')
        
        # Verificar si es categoría padre
        if categoria.parent is None:
            logger.info(f"Es una categoría padre: {categoria.name}")
            
            # Obtener subcategorías
            subcategorias = Category.objects.filter(parent=categoria, is_active=True)
            logger.info(f"Subcategorías encontradas: {[sub.name for sub in subcategorias]}")
            
            # Obtener productos de la categoría principal y subcategorías
            productos = Product.objects.filter(
                models.Q(category=categoria) |
                models.Q(category__in=subcategorias)
            ).distinct()
            
        else:
            logger.info(f"Es una subcategoría: {categoria.name}")
            productos = Product.objects.filter(category=categoria)
            subcategorias = None
        
        logger.info(f"Total productos encontrados: {productos.count()}")
        
        context = {
            'category': categoria,  # Cambiado a 'category' para coincidir con el template
            'categories': categories,
            'products': productos,  # Cambiado a 'products' para coincidir con el template
            'subcategories': subcategorias if 'subcategorias' in locals() else None,
        }
        
        return render(request, 'stock_smart/category_products.html', context)
        
    except Exception as e:
        logger.error(f"Error al cargar categoría: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return render(request, 'stock_smart/productos_lista.html', {
            'products': [],
            'categories': categories,
            'error_message': f"Error: {str(e)}"
        })

@login_required
def checkout_direct(request, product_id):
    product = get_object_or_404(Product, id=product_id)
    # Crear un CartItem temporal o redirigir directamente al checkout
    cart_item = CartItem.objects.create(
        user=request.user,
        product=product,
        quantity=1
    )
    # Redirigir al proceso de checkout
    return redirect('stock_smart:cart_view')  # O a tu vista de checkout existente

def checkout_options(request, product_id=None):
    try:
        if not product_id:
            messages.error(request, 'No se especificó un producto')
            return redirect('stock_smart:productos_lista')
            
        product = get_object_or_404(Product, id=product_id)
        
        # Guardar explícitamente en la sesión
        request.session['product_id'] = product_id
        request.session.modified = True  # Forzar guardado de la sesión
        
        logger.info(f"Producto ID guardado en sesión: {product_id}")
        
        # 1. Precio base (incluye IVA)
        base_price = product.published_price
        
        # 2. Aplicar descuento si existe
        if product.discount_percentage > 0:
            discount = (base_price * Decimal(str(product.discount_percentage))) / Decimal('100')
            final_price = base_price - discount
        else:
            final_price = base_price
            
        # 3. Calcular IVA (que ya está incluido)
        price_without_iva = final_price / Decimal('1.19')
        iva_amount = final_price - price_without_iva
        
        # Debug de cálculos
        print(f"Precio base (con IVA): ${base_price}")
        print(f"Descuento: {product.discount_percentage}%")
        print(f"Precio final (con IVA): ${final_price}")
        print(f"Precio sin IVA: ${price_without_iva}")
        print(f"Monto IVA: ${iva_amount}")
        print(f"ID del producto en sesión: {request.session.get('product_id')}")
        
        context = {
            'product': product,
            'base_price': base_price,
            'final_price': final_price,
            'price_without_iva': price_without_iva,
            'iva': iva_amount,
            'total': final_price,
            'is_quick_buy': True,
            'cart_count': get_cart_count(request)
        }
        
        return render(request, 'stock_smart/checkout_options.html', context)
        
    except Exception as e:
        logger.error(f"Error en checkout_options: {str(e)}")
        messages.error(request, f'Error al procesar el checkout: {str(e)}')
        return redirect('stock_smart:productos_lista')

def checkout_guest(request, product_id):
    product = get_object_or_404(Product, id=product_id)
    context = {
        'product': product,
        'cart_count': get_cart_count(request),
    }
    return render(request, 'stock_smart/guest_checkout.html', context)
def standardize_cart(cart):
    """Estandariza el formato del carrito"""
    standardized_cart = {}
    for product_id, item in cart.items():
        # Ignorar entradas con product_id None o inválido
        if product_id == 'None' or not product_id:
            logger.warning(f"Ignorando entrada inválida en carrito: {product_id}")
            continue
            
        try:
            if isinstance(item, (int, str)):
                # Convertir formato antiguo a nuevo
                product = Product.objects.get(id=product_id)
                standardized_cart[str(product_id)] = {
                    'quantity': int(item),
                    'price': str(product.get_final_price),
                    'name': product.name
                }
            elif isinstance(item, dict):
                # Mantener formato nuevo
                standardized_cart[str(product_id)] = item
                
            logger.info(f"Producto {product_id} estandarizado correctamente")
        except Product.DoesNotExist:
            logger.warning(f"Producto {product_id} no encontrado, ignorando")
            continue
        except Exception as e:
            logger.error(f"Error al estandarizar producto {product_id}: {str(e)}")
            continue
            
    return standardized_cart

def add_to_cart(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            product_id = str(data.get('product_id'))
            
            logger.info("=== DEBUG ADD TO CART ===")
            logger.info(f"Sesión ID: {request.session.session_key}")
            logger.info(f"Product ID recibido: {product_id}")
            
            product = get_object_or_404(Product, id=product_id)
            logger.info(f"Producto encontrado: {product.name}")
            
            # Asegurarse de que existe un carrito en la sesión
            if 'cart' not in request.session:
                request.session['cart'] = {}
                logger.info("Nuevo carrito creado en sesión")
            
            cart = request.session.get('cart', {})
            # Estandarizar el carrito existente
            cart = standardize_cart(cart)
            logger.info(f"Carrito estandarizado: {cart}")
            
            # Agregar o actualizar producto
            if product_id in cart:
                cart[product_id]['quantity'] += 1
                logger.info(f"Incrementada cantidad para producto {product_id}")
            else:
                cart[product_id] = {
                    'quantity': 1,
                    'price': str(product.get_final_price),
                    'name': product.name
                }
                logger.info(f"Nuevo producto agregado al carrito: {cart[product_id]}")
            
            # Guardar carrito actualizado
            request.session['cart'] = cart
            request.session.modified = True
            
            logger.info(f"Carrito actualizado: {cart}")
            cart_count = sum(item['quantity'] for item in cart.values())
            logger.info(f"Total items en carrito: {cart_count}")
            logger.info("=== FIN DEBUG ===")
            
            return JsonResponse({
                'success': True,
                'cart_count': cart_count
            })
            
        except Exception as e:
            logger.error(f"ERROR en add_to_cart: {str(e)}")
            return JsonResponse({
                'success': False,
                'error': str(e)
            })
    
    return JsonResponse({
        'success': False,
        'error': 'Método no permitido'
    })

@login_required
def user_checkout(request):
    try:
        # Obtener el carrito
        cart = request.session.get('cart', {})
        cart_items = []
        total = Decimal('0')
        
        # Procesar items del carrito
        for product_id, item_data in cart.items():
            product = get_object_or_404(Product, id=product_id)
            quantity = item_data['quantity']
            price = Decimal(item_data['price'])
            item_total = price * quantity
            
            cart_items.append({
                'product': product,
                'quantity': quantity,
                'price': price,
                'total': item_total
            })
            total += item_total
        
        # Obtener datos del usuario
        user = request.user
        context = {
            'cart_items': cart_items,
            'total': total,
            'user': user,
            'cart_count': sum(item['quantity'] for item in cart.values())
        }
        
        return render(request, 'stock_smart/user_checkout.html', context)
        
    except Exception as e:
        print(f"Error en user_checkout: {str(e)}")
        return redirect('stock_smart:cart')

def cart_checkout_options(request):
    try:
        cart = request.session.get('cart', {})
        if not cart:
            messages.warning(request, 'Tu carrito está vacío')
            return redirect('stock_smart:cart')
            
        cart_items = []
        total = Decimal('0')
        
        # Procesar items del carrito
        for product_id, item_data in cart.items():
            try:
                product = Product.objects.get(id=product_id)
                quantity = item_data['quantity']
                price = Decimal(item_data['price'])
                item_total = price * quantity
                
                cart_items.append({
                    'product': product,
                    'quantity': quantity,
                    'price': price,
                    'total': item_total
                })
                
                total += item_total
                
            except Product.DoesNotExist:
                continue
        
        # Calcular IVA
        iva = total * Decimal('0.19')
        total_con_iva = total + iva
        
        context = {
            'cart_items': cart_items,
            'subtotal': total,
            'iva': iva,
            'total': total_con_iva,
            'cart_count': sum(item['quantity'] for item in cart.values())
        }
        
        return render(request, 'stock_smart/cart_checkout_options.html', context)
        
    except Exception as e:
        print(f"Error en cart_checkout_options: {str(e)}")
        return redirect('stock_smart:cart')

@login_required
def user_cart_checkout(request):
    try:
        cart = request.session.get('cart', {})
        if not cart:
            return redirect('stock_smart:cart')
            
        # Reutilizar lógica existente pero con template específico
        cart_items = []
        total = Decimal('0')
        
        for product_id, item_data in cart.items():
            product = get_object_or_404(Product, id=product_id)
            quantity = item_data['quantity']
            price = Decimal(item_data['price'])
            item_total = price * quantity
            
            cart_items.append({
                'product': product,
                'quantity': quantity,
                'price': price,
                'total': item_total
            })
            total += item_total
        
        context = {
            'cart_items': cart_items,
            'total': total,
            'user': request.user,
            'cart_count': sum(item['quantity'] for item in cart.values())
        }
        
        return render(request, 'stock_smart/user_cart_checkout.html', context)
        
    except Exception as e:
        print(f"Error en user_cart_checkout: {str(e)}")
        return redirect('stock_smart:cart')

def guest_cart_checkout(request):
    try:
        cart = request.session.get('cart', {})
        if not cart:
            return redirect('stock_smart:cart')
            
        # Similar a guest_checkout pero con template específico
        cart_items = []
        total = Decimal('0')
        
        for product_id, item_data in cart.items():
            product = get_object_or_404(Product, id=product_id)
            quantity = item_data['quantity']
            price = Decimal(item_data['price'])
            item_total = price * quantity
            
            cart_items.append({
                'product': product,
                'quantity': quantity,
                'price': price,
                'total': item_total
            })
            total += item_total
        
        context = {
            'cart_items': cart_items,
            'total': total,
            'cart_count': sum(item['quantity'] for item in cart.values())
        }
        
        return render(request, 'stock_smart/guest_cart_checkout.html', context)
        
    except Exception as e:
        print(f"Error en guest_cart_checkout: {str(e)}")
        return redirect('stock_smart:cart')

def validate_product(request, product_id):
    if request.method == 'POST':
        try:
            product = get_object_or_404(Product, id=product_id)
            
            # Validar stock
            if product.stock <= 0:
                return JsonResponse({
                    'success': False,
                    'message': 'Producto sin stock disponible'
                })
            
            # Calcular precio final
            price = product.published_price
            if product.discount_percentage > 0:
                discount = (price * product.discount_percentage) / Decimal('100')
                price = price - discount
            
            # Validar precio
            if price <= 0:
                return JsonResponse({
                    'success': False,
                    'message': 'Precio no válido'
                })
            
            return JsonResponse({
                'success': True,
                'product': {
                    'id': product.id,
                    'name': product.name,
                    'price': float(price),
                    'stock': product.stock,
                    'discount': product.discount_percentage
                }
            })
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': str(e)
            })
            
    return JsonResponse({'success': False, 'message': 'Método no permitido'})

@csrf_exempt  # Necesario para recibir POST de Flow
def payment_confirm(request):
    try:
        logger.info("="*50)
        logger.info("INICIANDO PAYMENT CONFIRM")
        logger.info(f"Método: {request.method}")
        logger.info(f"POST data: {request.POST}")
        
        if request.method != 'POST':
            logger.error("Método no permitido")
            return HttpResponse('Método no permitido', status=405)
        
        # Obtener token
        token = request.POST.get('token')
        logger.info(f"Token recibido: {token}")
        
        if not token:
            logger.error("No se recibió token de Flow")
            return HttpResponse('Token no recibido', status=400)
        try:
            # Buscar orden por token
            order = Order.objects.get(flow_token=token)
            
            # Verificar estado del pago
            flow_service = FlowPaymentService()
            payment_status = flow_service.get_payment_status(token)
            
            if payment_status.get('status') == 2:  # Pago exitoso
                # Actualizar estado de la orden
                order.status = 'paid'
                order.save()
                
                logger.info(f"Pago confirmado para orden: {order.order_number}")
                return HttpResponse('OK', status=200)
            else:
                logger.error(f"Estado de pago inválido: {payment_status}")
                return HttpResponse('Estado de pago inválido', status=400)
                
        except Order.DoesNotExist:
            logger.error(f"No se encontró orden para el token: {token}")
            return HttpResponse('Orden no encontrada', status=404)
            
    except Exception as e:
        logger.error(f"Error en payment_confirm: {str(e)}")
        return HttpResponse('Error interno', status=500)

def detalle_producto(request, producto_id):
    try:
        product = get_object_or_404(Product, id=producto_id)
        
        # Guardar el producto en la sesión cuando se ve el detalle
        request.session['product_id'] = product.id
        logger.info(f"Producto guardado en sesión: {product.id}")
        
        context = {
            'product': product,
        }
        
        return render(request, 'stock_smart/detalle_producto.html', context)
        
    except Exception as e:
        logger.error(f"Error en detalle_producto: {str(e)}")
        messages.error(request, 'Error al mostrar el producto')
        return redirect('stock_smart:productos_lista')

def iniciar_checkout(request, producto_id):
    try:
        # Obtener el producto
        product = get_object_or_404(Product, id=producto_id)
        
        # Guardar en sesión
        request.session['product_id'] = product.id
        logger.info(f"Producto guardado en sesión: {product.id}")
        
        # Redirigir al checkout
        return redirect('stock_smart:guest_checkout')
        
    except Exception as e:
        logger.error(f"Error al iniciar checkout: {str(e)}")
        messages.error(request, 'Error al iniciar el proceso de compra')
        return redirect('stock_smart:productos_lista')

def update_cart_quantity(request):
    try:
        logger.info("Actualizando cantidad en carrito")
        product_id = request.POST.get('product_id')
        new_quantity = int(request.POST.get('quantity', 1))
        cart = request.session.get('cart', {})
        
        if product_id in cart:
            # Corregimos el paréntesis faltante
            item_total = int(float(cart[product_id]['price'])) * new_quantity
            cart[product_id]['quantity'] = new_quantity
            cart[product_id]['total'] = item_total
            
            request.session['cart'] = cart
            request.session.modified = True
            
            # Calcular nuevo total del carrito
            cart_total = sum(item['total'] for item in cart.values())
            
            logger.info(f"Carrito actualizado: Producto {product_id}, Nueva cantidad: {new_quantity}")
            
            return JsonResponse({
                'success': True,
                'new_quantity': new_quantity,
                'item_total': item_total,
                'cart_total': cart_total
            })
    except Exception as e:
        logger.error(f"Error al actualizar carrito: {str(e)}")
        return JsonResponse({'success': False, 'error': str(e)})

def payment_error(request):
    try:
        logger.info("="*50)
        logger.info("ERROR EN PAGO")
        logger.info(f"GET params: {request.GET}")
        
        error_message = request.GET.get('message', 'Error en el proceso de pago')
        order_id = request.session.get('order_id')
        
        context = {
            'error_message': error_message,
            'order_id': order_id
        }
        
        if order_id:
            try:
                order = Order.objects.get(id=order_id)
                context['order'] = order
                logger.info(f"Orden encontrada: {order.order_number}")
            except Order.DoesNotExist:
                logger.error(f"No se encontró la orden con ID: {order_id}")
        
        return render(request, 'stock_smart/payment_error.html', context)
        
    except Exception as e:
        logger.error(f"Error en payment_error view: {str(e)}")
        logger.error(traceback.format_exc())
        messages.error(request, 'Error al mostrar la página de error de pago')
        return redirect('stock_smart:productos_lista')

class ProductosPorCategoria(ListView):
    model = Product
    template_name = 'stock_smart/productos_lista.html'
    context_object_name = 'productos'
    paginate_by = 12

    def get_queryset(self):
        queryset = Product.objects.filter(active=True)
        query = self.request.GET.get('q')
        
        if query:
            logger.info(f"Búsqueda realizada: {query}")
            queryset = queryset.filter(
                Q(name__icontains=query) |
                Q(description__icontains=query) |
                Q(category__name__icontains=query) |
                Q(brand__name__icontains=query)
            ).distinct()
            
            logger.info(f"Resultados encontrados: {queryset.count()}")
        
        return queryset.order_by('-created_at')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['search_query'] = self.request.GET.get('q', '')
        return context

class ProductosListaView(ListView):  # Cambiamos a PascalCase para la clase
    model = Product
    template_name = 'stock_smart/productos_lista.html'
    context_object_name = 'productos'
    paginate_by = 12

    def get_queryset(self):
        queryset = Product.objects.filter(active=True)
        query = self.request.GET.get('q')
        
        if query:
            logger.info(f"Búsqueda realizada: {query}")
            queryset = queryset.filter(
                Q(name__icontains=query) |
                Q(description__icontains=query) |
                Q(category__name__icontains=query) |
                Q(brand__name__icontains=query)
            ).distinct()
            
            logger.info(f"Resultados encontrados: {queryset.count()}")
        
        return queryset.order_by('-created_at')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['search_query'] = self.request.GET.get('q', '')
        return context

class CheckoutOptionsView(View):
    template_name = 'stock_smart/checkout_options.html'

    def get(self, request, product_id):
        try:
            # Obtener el producto
            product = get_object_or_404(Product, id=product_id, active=True)
            logger.info(f"Iniciando compra rápida para producto: {product.name}")

            # Calcular precios
            base_price = product.published_price
            discount_percentage = product.discount_percentage
            
            if discount_percentage > 0:
                final_price = product.final_price
            else:
                final_price = base_price

            iva = final_price * Decimal('0.19')
            total = final_price + iva

            context = {
                'product': product,
                'base_price': base_price,
                'discount_percentage': discount_percentage,
                'final_price': final_price,
                'iva': iva,
                'total': total
            }

            # Guardar el producto en sesión para el proceso de checkout
            request.session['checkout_product_id'] = product_id
            logger.info(f"Producto {product_id} guardado en sesión para checkout")

            return render(request, self.template_name, context)

        except Product.DoesNotExist:
            logger.error(f"Producto no encontrado: {product_id}")
            messages.error(request, "El producto no está disponible.")
            return redirect('stock_smart:productos_lista')
        except Exception as e:
            logger.error(f"Error en checkout options: {str(e)}")
            messages.error(request, "Ha ocurrido un error. Por favor, intenta nuevamente.")
            return redirect('stock_smart:productos_lista')

class CartOptionsCheckoutView(View):
    def get(self, request):
        logger.info("="*50)
        logger.info("INICIANDO CREACIÓN DE ORDEN")
        
        try:
            cart = request.session.get('cart', {})
            
            if not cart:
                messages.warning(request, "Tu carrito está vacío")
                return redirect('stock_smart:cart')

            # Calcular totales
            products_data = []
            subtotal = Decimal('0')
            
            for product_id, item_data in cart.items():
                try:
                    product = Product.objects.get(id=int(product_id))
                    quantity = int(item_data.get('quantity', 0))
                    
                    # Calcular precio con descuento si existe
                    if product.discount_percentage > 0:
                        price = product.price * (1 - product.discount_percentage/100)
                    else:
                        price = product.price
                        
                    item_total = price * quantity
                    subtotal += item_total
                    
                    products_data.append({
                        'product': product,
                        'quantity': quantity,
                        'price': price,
                        'total': item_total
                    })
                    
                    logger.info(f"Producto agregado: {product.name}")
                    logger.info(f"Cantidad: {quantity}")
                    logger.info(f"Precio unitario: ${price}")
                    logger.info(f"Total item: ${item_total}")
                    
                except Product.DoesNotExist:
                    logger.error(f"Producto {product_id} no encontrado")
                    continue
                except Exception as e:
                    logger.error(f"Error procesando producto {product_id}: {str(e)}")
                    continue

            # Calcular IVA y total
            iva = subtotal * Decimal('0.19')
            total = subtotal + iva
            
            logger.info("\nTotales de la orden:")
            logger.info(f"Subtotal: ${subtotal}")
            logger.info(f"IVA: ${iva}")
            logger.info(f"Total: ${total}")

            # Crear orden
            order = Order.objects.create(
                order_number=generate_order_number(),
                subtotal=subtotal,
                iva=iva,
                total=total,
                status='pending'
            )
            
            # Crear items de la orden
            for item in products_data:
                OrderItem.objects.create(
                    order=order,
                    product=item['product'],
                    quantity=item['quantity'],
                    price=item['price'],
                    total=item['total']
                )
            # Guardar ID de orden en sesión
            request.session['order_id'] = order.id
            
            logger.info(f"Orden creada: #{order.order_number}")
            return redirect('stock_smart:guest_cart_checkout')
            
        except Exception as e:
            logger.error(f"Error creando orden: {str(e)}")
            logger.error(traceback.format_exc())
            messages.error(request, "Error al procesar el checkout")
            return redirect('stock_smart:cart')

class GuestCartCheckoutView(View):
    template_name = 'stock_smart/guest_cart_checkout.html'
    
    def get(self, request):
        logger.info("="*50)
        logger.info("INICIANDO GUEST CART CHECKOUT")
        
        try:
            # Obtener orden de la sesión
            order_id = request.session.get('order_id')
            logger.info(f"Buscando orden: {order_id}")
            
            if not order_id:
                messages.warning(request, "No se encontró la orden")
                return redirect('stock_smart:cart')
            
            # Obtener datos de la orden
            order = Order.objects.get(id=order_id)
            logger.info(f"Orden encontrada: {order.order_number}")
            
            context = {
                'order': order,
                'subtotal': order.subtotal or 0,
                'iva': order.iva or 0,
                'total': order.total or 0,
            }
            
            logger.info("Totales de la orden:")
            logger.info(f"Subtotal: ${context['subtotal']}")
            logger.info(f"IVA: ${context['iva']}")
            logger.info(f"Total: ${context['total']}")
            
            return render(request, self.template_name, context)
            
        except Order.DoesNotExist:
            logger.error(f"Orden {order_id} no encontrada")
            messages.error(request, "Orden no encontrada")
            return redirect('stock_smart:cart')
        except Exception as e:
            logger.error(f"Error en guest checkout: {str(e)}")
            logger.error(traceback.format_exc())
            messages.error(request, "Error al procesar el checkout")
            return redirect('stock_smart:cart')
    
    def post(self, request):
        logger.info("="*50)
        logger.info("PROCESANDO FORMULARIO CHECKOUT")
        
        try:
            # Obtener orden
            order_id = request.session.get('order_id')
            order = Order.objects.get(id=order_id)
            
            # Actualizar datos de la orden
            order.first_name = request.POST.get('first_name')
            order.last_name = request.POST.get('last_name')
            order.rut = request.POST.get('rut')
            order.phone = request.POST.get('phone')
            order.email = request.POST.get('email')
            order.shipping_method = request.POST.get('shipping_method')
            order.payment_method = request.POST.get('payment_method')
            
            # Si es envío Starken
            if order.shipping_method == 'starken':
                order.address = request.POST.get('address')
                order.region = request.POST.get('region')
                order.comuna = request.POST.get('comuna')
                order.shipping_notes = request.POST.get('shipping_notes')
                order.shipping_cost = Decimal('3990')
                order.total += order.shipping_cost
            
            order.save()
            logger.info(f"Orden {order.order_number} actualizada")
            
            # Redireccionar según método de pago
            if order.payment_method == 'flow':
                return redirect('stock_smart:flow_payment')
            else:
                return redirect('stock_smart:bank_transfer')
                
        except Exception as e:
            logger.error(f"Error procesando formulario: {str(e)}")
            logger.error(traceback.format_exc())
            messages.error(request, "Error al procesar el formulario")
            return self.get(request)

class CartPaymentView(View):
    template_name = 'stock_smart/cart_payment.html'

    def get(self, request):
        logger.info("Iniciando vista de pago del carrito")
        try:
            # Obtener la orden de la sesión
            order_id = request.session.get('order_id')
            if not order_id:
                logger.warning("No se encontró orden en la sesión")
                messages.error(request, "No se encontró la orden")
                return redirect('stock_smart:cart')

            order = get_object_or_404(Order, id=order_id)
            
            # Verificar que la orden esté pendiente
            if order.status != 'pending':
                logger.warning(f"Intento de pago para orden no pendiente: {order.order_number}")
                messages.error(request, "Esta orden ya no está disponible para pago")
                return redirect('stock_smart:cart')

            # Preparar datos para Flow
            flow_service = FlowPaymentService()
            payment_data = {
                'commerceOrder': order.order_number,
                'subject': f"Orden {order.order_number}",
                'currency': 'CLP',
                'amount': int(order.total),
                'email': order.email,
                'urlConfirmation': request.build_absolute_uri(reverse('stock_smart:cart_payment_confirm')),
                'urlReturn': request.build_absolute_uri(reverse('stock_smart:cart_payment_return'))
            }

            # Crear orden en Flow
            flow_response = flow_service.create_payment(payment_data)
            
            if flow_response.get('url'):
                logger.info(f"Pago Flow creado para orden {order.order_number}")
                return redirect(flow_response['url'])
            else:
                logger.error(f"Error creando pago Flow: {flow_response.get('error', 'Unknown error')}")
                messages.error(request, "Error al procesar el pago. Por favor, intente nuevamente.")
                return redirect('stock_smart:cart')

        except Order.DoesNotExist:
            logger.error(f"Orden no encontrada: {order_id}")
            messages.error(request, "Orden no encontrada")
            return redirect('stock_smart:cart')
        except Exception as e:
            logger.error(f"Error en vista de pago: {str(e)}")
            messages.error(request, "Ocurrió un error al procesar el pago")
            return redirect('stock_smart:cart')
        
        
class CartPaymentConfirmView(View):
    @csrf_exempt
    def post(self, request):
        logger.info("Recibiendo confirmación de pago Flow")
        try:
            # Obtener datos de Flow
            flow_service = FlowPaymentService()
            payment_data = flow_service.get_payment_status(request.POST)
            
            if not payment_data:
                logger.error("No se recibieron datos de pago de Flow")
                return HttpResponse(status=400)

            # Obtener la orden
            order = Order.objects.get(order_number=payment_data['commerceOrder'])
            
            # Actualizar estado según respuesta de Flow
            if payment_data['status'] == 2:  # Pago exitoso
                order.status = 'paid'
                order.payment_date = timezone.now()
                order.payment_id = payment_data['flowOrder']
                order.save()
                
                # Actualizar stock
                for item in order.orderitem_set.all():
                    product = item.product
                    product.stock -= item.quantity
                    product.save()
                    
                # Limpiar carrito de la sesión
                if 'cart' in request.session:
                    del request.session['cart']
                if 'order_id' in request.session:
                    del request.session['order_id']
                request.session.modified = True
                
                logger.info(f"Pago confirmado para orden {order.order_number}")
                
                # Enviar email de confirmación
                try:
                    send_confirmation_email(order)
                except Exception as e:
                    logger.error(f"Error enviando email de confirmación: {str(e)}")
                
            else:
                order.status = 'failed'
                order.save()
                logger.warning(f"Pago fallido para orden {order.order_number}")
            
            return HttpResponse(status=200)

        except Exception as e:
            logger.error(f"Error en confirmación de pago: {str(e)}")
            return HttpResponse(status=500)

class CartPaymentReturnView(View):
    template_name = 'stock_smart/cart_payment_return.html'

    def get(self, request):
        logger.info("Usuario retornando de Flow")
        try:
            # Obtener datos de Flow
            flow_service = FlowPaymentService()
            payment_data = flow_service.get_payment_status(request.GET)
            
            if not payment_data:
                logger.error("No se recibieron datos de retorno de Flow")
                messages.error(request, "No se pudo verificar el estado del pago")
                return redirect('stock_smart:cart')

            # Obtener la orden
            order = Order.objects.get(order_number=payment_data['commerceOrder'])
            
            context = {
                'order': order,
                'payment_status': payment_data['status'],
                'flow_order': payment_data['flowOrder']
            }
            
            if payment_data['status'] == 2:  # Pago exitoso
                messages.success(request, "¡Pago realizado con éxito!")
                logger.info(f"Usuario retornó con pago exitoso para orden {order.order_number}")
            else:
                messages.error(request, "El pago no pudo ser procesado")
                logger.warning(f"Usuario retornó con pago fallido para orden {order.order_number}")
            
            return render(request, self.template_name, context)

        except Exception as e:
            logger.error(f"Error en retorno de pago: {str(e)}")
            messages.error(request, "Ocurrió un error al procesar el pago")
            return redirect('stock_smart:cart')
        
        
class ProcessCartCheckoutView(View):
    def get(self, request):
        logger.info("Iniciando procesamiento de pago del carrito")
        try:
            # Obtener orden de la sesión
            order_id = request.session.get('order_id')
            if not order_id:
                logger.warning("No se encontró orden en la sesión")
                messages.error(request, "No se encontró la orden")
                return redirect('stock_smart:cart')

            order = get_object_or_404(Order, id=order_id)
            
            # Verificar que la orden esté pendiente
            if order.status != 'pending':
                logger.warning(f"Intento de pago para orden no pendiente: {order.order_number}")
                messages.error(request, "Esta orden ya no está disponible para pago")
                return redirect('stock_smart:cart')

            # Preparar datos para Flow
            flow_data = {
                'commerceOrder': order.order_number,
                'subject': f"Orden {order.order_number}",
                'currency': 'CLP',
                'amount': int(order.total),
                'email': order.email,
                'urlConfirmation': request.build_absolute_uri(reverse('stock_smart:cart_payment_confirm')),
                'urlReturn': request.build_absolute_uri(reverse('stock_smart:cart_payment_return'))
            }

            # Crear orden en Flow
            flow_service = FlowPaymentService()
            flow_response = flow_service.create_payment(flow_data)
            
            if flow_response.get('url'):
                logger.info(f"Redirigiendo a Flow para orden {order.order_number}")
                
                # Guardar token de Flow en la orden
                order.flow_token = flow_response.get('token')
                order.save()
                
                return redirect(flow_response['url'])
            else:
                logger.error(f"Error creando pago Flow: {flow_response.get('error', 'Unknown error')}")
                messages.error(request, "Error al procesar el pago. Por favor, intente nuevamente.")
                return redirect('stock_smart:cart')

        except Order.DoesNotExist:
            logger.error(f"Orden no encontrada: {order_id}")
            messages.error(request, "Orden no encontrada")
            return redirect('stock_smart:cart')
        except Exception as e:
            logger.error(f"Error en procesamiento de pago: {str(e)}")
            logger.error(traceback.format_exc())
            messages.error(request, "Ocurrió un error al procesar el pago")
            return redirect('stock_smart:cart')
        
      



class TerminosView(View):
    def get(self, request):
        logger.info("Accediendo a términos y condiciones")
        return render(request, 'stock_smart/terminos.html')

class TrackingView(View):
    template_name = 'stock_smart/seguimiento.html'
    
    def get(self, request):
        logger.info("="*50)
        logger.info("INICIANDO BÚSQUEDA DE ORDEN")
        
        try:
            order_number = request.GET.get('order_number')
            logger.info(f"Buscando orden número: {order_number}")
            
            if not order_number:
                logger.info("No se proporcionó número de orden")
                return render(request, self.template_name)

            # Consulta SQL directa para obtener la orden
            with connection.cursor() as cursor:
                # Primero, obtener los datos de la orden
                cursor.execute("""
                    SELECT 
                        id, order_number, status, payment_status, 
                        shipping_method, first_name, last_name, 
                        email, phone, address, comuna, region,
                        shipping_cost, subtotal, iva, total,
                        created_at, shipping_notes
                    FROM stock_smart_order 
                    WHERE order_number = %s
                """, [order_number])
                
                order_row = cursor.fetchone()
                
                if order_row:
                    # Convertir los resultados en un diccionario
                    columns = [col[0] for col in cursor.description]
                    order = dict(zip(columns, order_row))
                    
                    # Obtener los items de la orden
                    cursor.execute("""
                        SELECT 
                            p.name,
                            oi.quantity,
                            oi.price,
                            (oi.quantity * oi.price) as total
                        FROM stock_smart_orderitem oi
                        JOIN stock_smart_product p ON oi.product_id = p.id
                        WHERE oi.order_id = %s
                    """, [order['id']])
                    
                    items = []
                    for item_row in cursor.fetchall():
                        items.append({
                            'name': item_row[0],
                            'quantity': item_row[1],
                            'price': item_row[2],
                            'total': item_row[3]
                        })
                    
                    # Formatear estados para display
                    order['status'] = self.get_status_display(order['status'])
                    order['payment_status'] = self.get_payment_status_display(order['payment_status'])
                    order['shipping_method'] = self.get_shipping_method_display(order['shipping_method'])
                    
                    context = {
                        'order': order,
                        'items': items
                    }
                    
                    logger.info(f"Orden encontrada: {order['order_number']}")
                    return render(request, self.template_name, context)
                else:
                    logger.warning(f"No se encontró la orden: {order_number}")
                    messages.error(request, "No se encontró la orden especificada")
                    return render(request, self.template_name)
                    
        except Exception as e:
            logger.error(f"Error al buscar orden: {str(e)}")
            logger.error(traceback.format_exc())
            messages.error(request, "Error al buscar la orden")
            return render(request, self.template_name)

    def get_status_display(self, status):
        status_choices = {
            'pending': 'Pendiente',
            'processing': 'Procesando',
            'shipped': 'Enviado',
            'delivered': 'Entregado',
            'cancelled': 'Cancelado'
        }
        return status_choices.get(status, status)

    def get_payment_status_display(self, status):
        payment_status_choices = {
            'pending': 'Pendiente',
            'completed': 'Completado',
            'failed': 'Fallido',
            'refunded': 'Reembolsado'
        }
        return payment_status_choices.get(status, status)

    def get_shipping_method_display(self, method):
        shipping_method_choices = {
            'pickup': 'Retiro en tienda',
            'starken': 'Envío Starken'
        }
        return shipping_method_choices.get(method, method)

@csrf_protect
def payment_form(request):
    """Vista para mostrar el formulario de pago"""
    try:
        logger.info("="*50)
        logger.info("INICIANDO FORMULARIO DE PAGO")
        
        # Obtener datos de la orden desde la sesión
        order_id = request.session.get('order_id')
        logger.info(f"Order ID en sesión: {order_id}")
        
        if not order_id:
            logger.error("No se encontró order_id en sesión")
            messages.error(request, 'No se encontró la orden')
            return redirect('stock_smart:productos_lista')
            
        order = get_object_or_404(Order, id=order_id)
        logger.info(f"Orden encontrada: {order.order_number}")
        
        context = {
            'order': order,
            'total': order.total_amount,
            'iva': order.total_amount * Decimal('0.19'),
            'subtotal': order.total_amount / Decimal('1.19')
        }
        
        return render(request, 'stock_smart/payment_form.html', context)
        
    except Exception as e:
        logger.error(f"Error en payment_form: {str(e)}")
        logger.error(traceback.format_exc())
        messages.error(request, 'Error al cargar el formulario de pago')
        return redirect('stock_smart:checkout_error')

@csrf_protect
def payment_success(request):
    logger.info('Accediendo a payment_success')
    try:
        logger.info("="*50)
        logger.info("PROCESANDO PAGO EXITOSO")
        
        # Obtener order_id de la sesión
        order_id = request.session.get('order_id')
        logger.info(f"Order ID en sesión: {order_id}")
        
        if not order_id:
            logger.warning("No se encontró order_id en sesión")
            messages.warning(request, 'No se encontró información de la orden')
            # En lugar de redireccionar, renderizamos el template con mensaje de éxito genérico
            return render(request, 'stock_smart/payment_success.html', {})
        
        try:
            order = Order.objects.select_related().get(id=order_id)
        except Order.DoesNotExist:
            logger.error(f"No se encontró la orden con ID: {order_id}")
            messages.error(request, 'Orden no encontrada')
            return render(request, 'stock_smart/payment_success.html', {})
        
        # Si la orden ya está pagada, solo mostrar la página de éxito
        if order.status == 'PAID':
            return render(request, 'stock_smart/payment_success.html', {'order': order})
        
        try:
            # Iniciar transacción para asegurar la integridad de los datos
            with transaction.atomic():
                # Actualizar estado de la orden
                order.status = 'PAID'
                order.payment_date = timezone.now()
                
                # Actualizar stock de productos
                for item in order.orderitem_set.all():
                    product = item.product
                    if product.stock >= item.quantity:
                        product.stock -= item.quantity
                        product.save()
                        logger.info(f"Stock actualizado para producto {product.id}: {product.stock}")
                    else:
                        raise ValueError(f"Stock insuficiente para {product.name}")
                
                order.save()
                logger.info(f"Orden {order.order_number} actualizada correctamente")
                
                # Limpiar sesión
                request.session.pop('order_id', None)
                request.session.pop('cart_id', None)
                request.session.modified = True
                
                # Intentar enviar email
                try:
                    send_confirmation_email(order)
                    logger.info("Correo de confirmación enviado")
                except Exception as e:
                    logger.error(f"Error al enviar correo: {str(e)}")
                
                messages.success(request, '¡Pago realizado con éxito!')
                
                return render(request, 'stock_smart/payment_success.html', {
                    'order': order,
                })
                
        except ValueError as ve:
            logger.error(f"Error de validación: {str(ve)}")
            messages.error(request, str(ve))
            return redirect('stock_smart:checkout_error')
            
    except Exception as e:
        logger.error(f"Error en payment_success: {str(e)}")
        logger.error(traceback.format_exc())
        messages.error(request, 'Error al procesar el pago')
        return redirect('stock_smart:checkout_error')

def send_confirmation_email(order):
    """Función auxiliar para enviar correo de confirmación"""
    try:
        subject = f'Confirmación de Pago - Orden #{order.order_number}'
        message = f"""
        ¡Gracias por tu compra!
        
        Detalles de la orden:
        Número de orden: {order.order_number}
        Total: ${order.total_amount}
        Estado: Pagado
        
        Pronto recibirás información sobre el envío.
        """
        
        send_mail(
            subject,
            message,
            'noreply@tusitio.com',
            [order.customer_email],
            fail_silently=False,
        )
    except Exception as e:
        logger.error(f"Error al enviar correo de confirmación: {str(e)}")
        # No relanzo la excepción para no interrumpir el flujo principal

@require_http_methods(["GET", "POST"])
def logout_view(request):
    try:
        logger.info("="*50)
        logger.info("INICIO PROCESO LOGOUT")
        logger.info(f"Usuario que cierra sesión: {request.user}")
        
        # Limpiar carrito de la sesión si existe
        if 'cart' in request.session:
            del request.session['cart']
            logger.info("Carrito eliminado de la sesión")
        
        # Realizar logout
        logout(request)
        logger.info("Logout ejecutado correctamente")
        
        # Mensaje de éxito
        messages.success(request, '¡Hasta pronto! Has cerrado sesión correctamente')
        logger.info("Mensaje de éxito agregado")
        
        # Redirección a inicio
        logger.info("Redirigiendo a página de inicio")
        return redirect('/')
        
    except Exception as e:
        logger.error("ERROR EN PROCESO LOGOUT")
        logger.error(f"Error: {str(e)}")
        logger.error(traceback.format_exc())
        messages.error(request, 'Ocurrió un error al cerrar sesión')
        return redirect('/')

def cart_update(request, product_id):
    try:
        logger.info(f"Iniciando actualización de carrito para producto {product_id}")
        
        if request.method == 'POST':
            cart = request.session.get('cart', {})
            quantity = int(request.POST.get('quantity', 1))
            
            logger.info(f"Actualizando cantidad: {quantity} para producto: {product_id}")
            
            # Actualizar cantidad en el carrito
            cart[str(product_id)] = quantity
            request.session['cart'] = cart
            request.session.modified = True
            
            logger.info("Carrito actualizado exitosamente")
            return JsonResponse({'status': 'success'})
        
        logger.warning(f"Método no permitido: {request.method}")
        return JsonResponse({'error': 'Método no permitido'}, status=405)
        
    except Exception as e:
        logger.error(f"Error en cart_update: {str(e)}")
        return JsonResponse({'error': str(e)}, status=400)

def clear_cart(request):
    request.session['cart'] = {}
    request.session.modified = True
    return JsonResponse({'status': 'success', 'message': 'Carrito limpiado'})

def mercadopago_success(request):
    try:
        logger.info("="*50)
        logger.info("PAGO MERCADOPAGO EXITOSO")
        logger.info(f"Parámetros recibidos: {request.GET}")
        
        payment_id = request.GET.get('payment_id')
        order_id = request.GET.get('external_reference')
        
        if order_id:
            order = Order.objects.get(id=order_id)
            order.status = 'paid'
            order.payment_id = payment_id
            order.save()
            
            logger.info(f"Orden {order_id} actualizada a estado 'paid'")
            messages.success(request, '¡Pago procesado exitosamente!')
            return render(request, 'stock_smart/payment_success.html', {'order': order})
            
    except Exception as e:
        logger.error(f"Error en mercadopago_success: {str(e)}")
        logger.error(traceback.format_exc())
        messages.error(request, 'Error al procesar la confirmación del pago')
    
    return redirect('stock_smart:productos_lista')


def mercadopago_failure(request):
    try:
        logger.info("="*50)
        logger.info("PAGO MERCADOPAGO FALLIDO")
        logger.info(f"Parámetros recibidos: {request.GET}")
        
        order_id = request.GET.get('external_reference')
        if order_id:
            order = Order.objects.get(id=order_id)
            order.status = 'failed'
            order.save()
            logger.info(f"Orden {order_id} actualizada a estado 'failed'")
        
        messages.error(request, 'El pago no pudo ser procesado')
        return render(request, 'stock_smart/payment_failure.html')
        
    except Exception as e:
        logger.error(f"Error en mercadopago_failure: {str(e)}")
        logger.error(traceback.format_exc())
        messages.error(request, 'Error al procesar el pago')
        return redirect('stock_smart:productos_lista')
def mercadopago_pending(request):
    try:
        logger.info("="*50)
        logger.info("PAGO MERCADOPAGO PENDIENTE")
        logger.info(f"Parámetros recibidos: {request.GET}")
        
        order_id = request.GET.get('external_reference')
        if order_id:
            order = Order.objects.get(id=order_id)
            order.status = 'pending'
            order.save()
            logger.info(f"Orden {order_id} actualizada a estado 'pending'")
        
        messages.warning(request, 'Tu pago está pendiente de confirmación')
        return render(request, 'stock_smart/payment_pending.html')
        
    except Exception as e:
        logger.error(f"Error en mercadopago_pending: {str(e)}")
        logger.error(traceback.format_exc())
        messages.error(request, 'Error al procesar el estado pendiente del pago')
        return redirect('stock_smart:home')

@csrf_exempt
@require_http_methods(["POST"])
def mercadopago_webhook(request):
    logger.info("="*50)
    logger.info("WEBHOOK MERCADOPAGO RECIBIDO")
    logger.info(f"Datos recibidos: {request.POST}")
    
    mp = MercadoPagoAdapter()
    if mp.process_webhook(request.POST):
        logger.info("Webhook procesado exitosamente")
        return HttpResponse(status=200)
    
    logger.error("Error al procesar webhook")
    return HttpResponse(status=400)
@require_http_methods(["POST"])
def mercadopago_create_preference(request):
    try:
        logger.info("="*50)
        logger.info("CREANDO PREFERENCIA MERCADOPAGO")
        
        # Imprimir el body completo de la solicitud
        logger.info(f"Request body raw: {request.body}")
        
        try:
            data = json.loads(request.body)
            logger.info(f"Datos parseados: {data}")
        except json.JSONDecodeError as e:
            logger.error(f"Error al parsear JSON: {str(e)}")
            return JsonResponse({
                'status': 'error',
                'message': 'Error en el formato de los datos'
            }, status=400)

        # Verificar que tenemos el product_id en la sesión
        product_id = request.session.get('product_id')
        logger.info(f"Product ID from session: {product_id}")
        
        if not product_id:
            logger.error("No se encontró product_id en la sesión")
            return JsonResponse({
                'status': 'error',
                'message': 'Producto no encontrado en la sesión'
            }, status=400)

        try:
            # Obtener el producto
            product = Product.objects.get(id=product_id)
            logger.info(f"Producto encontrado: {product.name}, Precio: {product.final_price}")

            # Crear la orden
            order_number = f'ORD-{timezone.now().strftime("%Y%m%d")}-{uuid.uuid4().hex[:8]}'
            
            order = Order.objects.create(
                order_number=order_number,
                customer_name=f"{data.get('nombre', '')} {data.get('apellido', '')}",
                customer_email=data.get('email', ''),
                customer_phone=data.get('telefono', ''),
                region=data.get('region', ''),
                ciudad=data.get('ciudad', ''),
                comuna=data.get('comuna', ''),
                shipping_address=data.get('direccion', ''),
                shipping_method=data.get('shipping', ''),
                payment_method='mercadopago',
                total_amount=product.final_price,
                status='pending_payment'
            )
            logger.info(f"Orden creada: {order.id}")

            # Crear item de orden
            order_item = OrderItem.objects.create(
                order=order,
                product=product,
                quantity=1,
                price=product.final_price
            )
            logger.info(f"Item de orden creado: {order_item.id}")

            # Crear preferencia de MercadoPago
            mp = MercadoPagoAdapter()
            logger.info("MercadoPago adapter creado")
            
            # Crear datos de preferencia
            preference_data = {
                "items": [{
                    "title": product.name,
                    "quantity": 1,
                    "currency_id": "CLP",
                    "unit_price": float(product.final_price)
                }],
                "external_reference": str(order.id),
                "back_urls": {
                    "success": settings.MERCADOPAGO_SUCCESS_URL,
                    "failure": settings.MERCADOPAGO_FAILURE_URL,
                    "pending": settings.MERCADOPAGO_PENDING_URL
                },
                "notification_url": settings.MERCADOPAGO_WEBHOOK_URL
            }
            logger.info(f"Datos de preferencia: {preference_data}")
            
            preference = mp.create_preference(order)
            logger.info(f"Respuesta de MercadoPago: {preference}")

            if preference and 'init_point' in preference:
                return JsonResponse({
                    'status': 'success',
                    'init_point': preference['init_point']
                })
            else:
                logger.error("No se recibió init_point en la respuesta")
                return JsonResponse({
                    'status': 'error',
                    'message': 'Error al crear preferencia de pago'
                }, status=500)

        except Product.DoesNotExist:
            logger.error(f"Producto no existe: {product_id}")
            return JsonResponse({
                'status': 'error',
                'message': 'Producto no encontrado'
            }, status=404)
        except Exception as e:
            logger.error(f"Error al crear orden o preferencia: {str(e)}")
            logger.error(traceback.format_exc())
            return JsonResponse({
                'status': 'error',
                'message': 'Error al procesar el pago'
            }, status=500)

    except Exception as e:
        logger.error(f"Error general: {str(e)}")
        logger.error(traceback.format_exc())
        return JsonResponse({
            'status': 'error',
            'message': str(e)
        }, status=500)

def payment_success(request):
    try:
        logger.info("="*50)
        logger.info("PAGO EXITOSO")
        logger.info(f"GET params: {request.GET}")
        
        # Obtener parámetros de la respuesta
        payment_data = {
            'collection_id': request.GET.get('collection_id'),
            'collection_status': request.GET.get('collection_status'),
            'payment_id': request.GET.get('payment_id'),
            'status': request.GET.get('status'),
            'external_reference': request.GET.get('external_reference'),
            'payment_type': request.GET.get('payment_type'),
            'merchant_order_id': request.GET.get('merchant_order_id'),
            'preference_id': request.GET.get('preference_id'),
            'site_id': request.GET.get('site_id'),
            'processing_mode': request.GET.get('processing_mode'),
            'merchant_account_id': request.GET.get('merchant_account_id')
        }
        
        logger.info(f"Datos de pago procesados: {payment_data}")
        
        # Actualizar la orden si existe
        if payment_data['external_reference']:
            try:
                order = Order.objects.get(id=payment_data['external_reference'])
                order.status = 'paid'  # Asegúrate de que este estado existe en tu modelo
                order.payment_id = payment_data['payment_id']
                order.payment_status = payment_data['status']
                order.save()
                logger.info(f"Orden {order.id} actualizada correctamente")
            except Order.DoesNotExist:
                logger.error(f"No se encontró la orden con ID {payment_data['external_reference']}")
            except Exception as e:
                logger.error(f"Error al actualizar la orden: {str(e)}")
        
        # Renderizar template de éxito
        return render(request, 'stock_smart/payment_success.html', {
            'payment_data': payment_data,
            'order_id': payment_data['external_reference']
        })
        
    except Exception as e:
        logger.error(f"Error en payment_success: {str(e)}")
        return render(request, 'stock_smart/payment_failure.html', {
            'error_message': 'Hubo un error al procesar la respuesta del pago'
        })

def payment_failure(request):
    try:
        logger.info("="*50)
        logger.info("PAGO FALLIDO")
        logger.info(f"GET params: {request.GET}")
        
        error_message = request.GET.get('error_message', 'El pago no pudo ser procesado')
        
        return render(request, 'stock_smart/payment_failure.html', {
            'error_message': error_message
        })
    except Exception as e:
        logger.error(f"Error en payment_failure: {str(e)}")
        return render(request, 'stock_smart/payment_failure.html', {
            'error_message': 'Error al procesar la respuesta del pago'
        })

def payment_pending(request):
    try:
        logger.info("="*50)
        logger.info("PAGO PENDIENTE")
        logger.info(f"GET params: {request.GET}")
        
        return render(request, 'stock_smart/payment_pending.html', {
            'payment_id': request.GET.get('payment_id'),
            'external_reference': request.GET.get('external_reference')
        })
    except Exception as e:
        logger.error(f"Error en payment_pending: {str(e)}")
        return render(request, 'stock_smart/payment_failure.html', {
            'error_message': 'Error al procesar el estado pendiente del pago'
        })

@csrf_exempt
def mercadopago_webhook(request):
    try:
        logger.info("="*50)
        logger.info("WEBHOOK MERCADOPAGO")
        logger.info(f"Method: {request.method}")
        logger.info(f"Headers: {request.headers}")
        logger.info(f"Body: {request.body}")
        
        return HttpResponse(status=200)
    except Exception as e:
        logger.error(f"Error en webhook: {str(e)}")
        return HttpResponse(status=500)