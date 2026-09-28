from decimal import Decimal
from django.db import migrations


def sanitizar_emprestimos(apps, schema_editor):
    Emprestimo = apps.get_model('estoque', 'Emprestimo')
    
    # 1. Se quantidade for nula, define como 1.00
    Emprestimo.objects.filter(quantidade__isnull=True).update(quantidade=Decimal('1.00'))
    
    # 2. Se quantidade_devolvida for nula, define como 0.00
    Emprestimo.objects.filter(quantidade_devolvida__isnull=True).update(quantidade_devolvida=Decimal('0.00'))
    
    # 3. Se já constava como totalmente devolvido, garante que quantidade_devolvida reflita a quantidade total
    for emp in Emprestimo.objects.filter(devolvido=True):
        if emp.quantidade_devolvida is None or emp.quantidade_devolvida == Decimal('0.00'):
            emp.quantidade_devolvida = emp.quantidade or Decimal('1.00')
            emp.save(update_fields=['quantidade_devolvida'])


class Migration(migrations.Migration):

    dependencies = [
        ('estoque', '0018_venda_descricao_adicional_venda_valor_adicional'),
    ]

    operations = [
        migrations.RunPython(sanitizar_emprestimos, migrations.RunPython.noop),
    ]
