# Generated by Django 5.1.3 on 2024-11-28 01:51

import django.db.models.deletion
import stock_smart.models
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('stock_smart', '0005_order_ciudad_order_comuna_order_observaciones_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='GuestOrder',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('order_number', models.CharField(max_length=9, unique=True)),
                ('status', models.CharField(choices=[('pending', 'En Curso'), ('paid', 'Pagado'), ('cancelled', 'Cancelado')], default='pending', max_length=20)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('first_name', models.CharField(max_length=100)),
                ('last_name', models.CharField(max_length=100)),
                ('rut', models.CharField(max_length=12)),
                ('phone', models.CharField(max_length=15)),
                ('email', models.EmailField(max_length=254)),
                ('shipping_method', models.CharField(choices=[('pickup', 'Retiro en Tienda'), ('starken', 'Envío Starken')], default='pickup', max_length=20)),
                ('address', models.CharField(blank=True, max_length=200, null=True)),
                ('region', models.CharField(blank=True, max_length=100, null=True)),
                ('comuna', models.CharField(blank=True, max_length=100, null=True)),
                ('shipping_notes', models.TextField(blank=True, null=True)),
                ('payment_method', models.CharField(choices=[('flow', 'Flow'), ('transfer', 'Transferencia Bancaria')], default='flow', max_length=20)),
                ('subtotal', models.DecimalField(decimal_places=2, max_digits=10)),
                ('iva', models.DecimalField(decimal_places=2, max_digits=10)),
                ('shipping_cost', models.DecimalField(decimal_places=2, default=0, max_digits=10)),
                ('total', models.DecimalField(decimal_places=2, max_digits=10)),
            ],
        ),
        migrations.AlterField(
            model_name='order',
            name='order_number',
            field=models.CharField(default=stock_smart.models.generate_order_number, max_length=20, unique=True),
        ),
        migrations.AlterField(
            model_name='order',
            name='payment_method',
            field=models.CharField(choices=[('flow', 'Pago con Flow'), ('transfer', 'Transferencia Bancaria')], max_length=20),
        ),
        migrations.AlterField(
            model_name='order',
            name='shipping_method',
            field=models.CharField(choices=[('pickup', 'Retiro en tienda'), ('starken', 'Envío por Starken')], max_length=20),
        ),
        migrations.CreateModel(
            name='GuestOrderItem',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('quantity', models.IntegerField()),
                ('price', models.DecimalField(decimal_places=2, max_digits=10)),
                ('total', models.DecimalField(decimal_places=2, max_digits=10)),
                ('order', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='items', to='stock_smart.guestorder')),
                ('product', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='stock_smart.product')),
            ],
        ),
    ]
