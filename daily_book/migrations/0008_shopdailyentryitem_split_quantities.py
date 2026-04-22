from django.db import migrations, models


def backfill_daily_entry_item_quantities(apps, schema_editor):
    ShopDailyEntryItem = apps.get_model('daily_book', 'ShopDailyEntryItem')
    for item in ShopDailyEntryItem.objects.all().iterator():
        base_quantity = item.quantity or 0
        item.paper_quantity = base_quantity
        item.finishing_quantity = base_quantity if item.finishing_id else 0
        item.save(update_fields=['paper_quantity', 'finishing_quantity'])


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('daily_book', '0007_finishingrate_side_shopdailyentryitem_finishing_rate_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='shopdailyentryitem',
            name='finishing_quantity',
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name='shopdailyentryitem',
            name='paper_quantity',
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.RunPython(backfill_daily_entry_item_quantities, noop_reverse),
    ]
