from django.urls import path
from . import views

urlpatterns = [
    path('', views.lista_produtos, name='lista_produtos'),
    path('novo/', views.criar_produto, name='criar_produto'),
    path('editar/<int:pk>/', views.editar_produto, name='editar_produto'),
    path('excluir/<int:pk>/', views.excluir_produto, name='excluir_produto'),
    path('emprestimos/', views.lista_emprestimos, name='lista_emprestimos'),
    path('emprestimos/novo/', views.registrar_emprestimo, name='registrar_emprestimo'),
    path('emprestimos/devolver/<int:pk>/', views.devolver_ferramenta, name='devolver_ferramenta'),
    path('saidas/', views.lista_saidas, name='lista_saidas'),
    path('saidas/nova/', views.registrar_saida, name='registrar_saida'),
]

