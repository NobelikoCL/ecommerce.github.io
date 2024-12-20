from django.contrib import admin
from .models import Order, OrderItem, Category, Product, Brand

class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    readonly_fields = ['product', 'quantity', 'price']

@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ['order_number', 'customer_name', 'status', 'total_amount', 'created_at']
    list_filter = ['status', 'shipping_method', 'created_at']
    search_fields = ['order_number', 'customer_name', 'customer_email']
    readonly_fields = ['order_number', 'created_at']
    
    fieldsets = [
        ('Información de Orden', {
            'fields': ('order_number', 'status', 'created_at')
        }),
        ('Cliente', {
            'fields': ('customer_name', 'customer_email', 'customer_phone')
        }),
        ('Envío', {
            'fields': ('shipping_method', 'shipping_cost', 'shipping_address')
        }),
        ('Producto y Precios', {
            'fields': ('product', 'base_price', 'discount_percentage', 'final_price', 
                      'iva_amount', 'total_amount')
        })
    ]
    inlines = [OrderItemInline]

@admin.register(OrderItem)
class OrderItemAdmin(admin.ModelAdmin):
    list_display = [
        'order',
        'product',
        'quantity',
        'price',
        'total'
    ]
    list_filter = ['order__status']
    search_fields = [
        'order__order_number',
        'product__name'
    ]
    readonly_fields = [
        'order',
        'product',
        'quantity',
        'price'
    ]

@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ['name', 'slug', 'parent', 'is_active']
    list_editable = ['is_active']
    prepopulated_fields = {'slug': ('name',)}
    search_fields = ['name']
    list_filter = ['is_active', 'parent']

@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ['name', 'category', 'brand', 'published_price', 'discount_percentage', 'stock', 'active', 'is_featured']
    list_filter = ['active', 'is_featured', 'category', 'brand']
    search_fields = ['name', 'description']
    prepopulated_fields = {'slug': ('name',)}
    list_editable = ['published_price', 'discount_percentage', 'stock', 'active', 'is_featured']
    
    fieldsets = (
        ('Información Básica', {
            'fields': ('name', 'slug', 'description', 'image')
        }),
        ('Categorización', {
            'fields': ('category', 'brand'),
            'description': 'La categoría es obligatoria'
        }),
        ('Precios y Stock', {
            'fields': ('published_price', 'discount_percentage', 'stock')
        }),
        ('Estado', {
            'fields': ('active', 'is_featured')
        }),
    )

@admin.register(Brand)
class BrandAdmin(admin.ModelAdmin):
    list_display = ['name', 'is_active']
    list_filter = ['is_active']
    search_fields = ['name']
    prepopulated_fields = {'slug': ('name',)}
