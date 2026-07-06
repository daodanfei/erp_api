from rest_framework import serializers
from .models import CashAccount, CashAccountTransaction, FinancialSnapshot, FinanceExportTask


class CashAccountTransactionSerializer(serializers.ModelSerializer):
    operator_name = serializers.CharField(source='operator.username', read_only=True)

    class Meta:
        model = CashAccountTransaction
        fields = '__all__'

class CashAccountSerializer(serializers.ModelSerializer):
    transactions = CashAccountTransactionSerializer(many=True, read_only=True)

    class Meta:
        model = CashAccount
        fields = '__all__'

class FinancialSnapshotSerializer(serializers.ModelSerializer):
    class Meta:
        model = FinancialSnapshot
        fields = '__all__'

class FinanceExportTaskSerializer(serializers.ModelSerializer):
    created_by_name = serializers.CharField(source='created_by.username', read_only=True)
    class Meta:
        model = FinanceExportTask
        fields = '__all__'
