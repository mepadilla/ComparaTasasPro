import threading
from datetime import datetime
import locale
import requests
from bs4 import BeautifulSoup
import re

# --- KIVYMD IMPORTS ---
from kivymd.app import MDApp
from kivy.uix.screenmanager import Screen
from kivymd.uix.list import TwoLineIconListItem, IconLeftWidget
from kivymd.uix.dialog import MDDialog
from kivymd.uix.button import MDFlatButton

# --- LÓGICA DE NEGOCIO ---
def obtener_cotizaciones():
    URL = "https://kaskogo.online/app/"
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        response = requests.get(URL, headers=headers, timeout=10)
        response.raise_for_status()
        response.encoding = 'utf-8'
        soup = BeautifulSoup(response.text, 'html.parser')
        contenedores = soup.find_all('div', class_='flex items-center justify-between p-4 rate-card rounded-lg shadow-md')
        cotizaciones = {}
        for item in contenedores:
            name_div = item.find('div')
            value_tag = item.find('span', class_='rate-value')
            if name_div and value_tag:
                nombre_sucio = name_div.text.strip()
                nombre = re.sub(r'^\W+\s*', '', nombre_sucio).strip()
                valor_texto = value_tag.text.strip()
                valor_limpio = re.sub(r'[^\d,]', '', valor_texto).replace(',', '.')
                try:
                    cotizaciones[nombre] = float(valor_limpio)
                except ValueError:
                    pass
        return cotizaciones
    except requests.exceptions.RequestException as e:
        print(f"❌ Error al conectar con el sitio web: {e}")
        return None

def calcular_precio_simplificado(
    costo_fob, porcentaje_costo_almacen, tasa_oficial, tasa_no_oficial,
    porcentaje_gastos, porcentaje_utilidad_neta, porcentaje_ventas_en_bs
):
    cta_usd = costo_fob * (1 + (porcentaje_costo_almacen / 100))
    porcentaje_margen_bruto_requerido = (porcentaje_gastos + porcentaje_utilidad_neta) / 100
    if (1 - porcentaje_margen_bruto_requerido) <= 0: raise ValueError("La suma de gastos y utilidad excede el 100%.")
    pvm_usd = cta_usd / (1 - porcentaje_margen_bruto_requerido)
    if tasa_no_oficial == 0: raise ValueError("La tasa no oficial no puede ser cero.")
    factor_perdida_cambiaria = ((tasa_no_oficial - tasa_oficial) / tasa_no_oficial) * (porcentaje_ventas_en_bs / 100)
    if (1 - factor_perdida_cambiaria) <= 0: raise ValueError("El factor de pérdida cambiaria es 100% o más.")
    pvd_ajustado_usd = pvm_usd / (1 - factor_perdida_cambiaria)
    return {
        "costo_total_en_almacen_cta_usd": cta_usd, "precio_venta_minimo_pvm_usd": pvm_usd,
        "factor_perdida_cambiaria_porcentual": factor_perdida_cambiaria * 100,
        "precio_venta_final_ajustado_pvd_usd": pvd_ajustado_usd
    }

# --- DEFINICIÓN DE PANTALLAS ---
class MenuScreen(Screen): pass
class TasasScreen(Screen): pass
class CalculadoraScreen(Screen):
    def realizar_calculo(self):
        app = MDApp.get_running_app()
        try:
            datos_producto = {
                "costo_fob": float(self.ids.costo_fob_input.text),
                "porcentaje_costo_almacen": float(self.ids.costo_almacen_input.text),
                "tasa_oficial": app.tasa_bcv,
                "tasa_no_oficial": app.tasa_no_oficial,
                "porcentaje_gastos": float(self.ids.gastos_input.text),
                "porcentaje_utilidad_neta": float(self.ids.utilidad_input.text),
                "porcentaje_ventas_en_bs": float(self.ids.ventas_bs_input.text)
            }
            if app.tasa_bcv == 0 or app.tasa_no_oficial == 0: raise ValueError("Las tasas no se han cargado.")
            resultados = calcular_precio_simplificado(**datos_producto)
            app.actualizar_labels_resultados(self, resultados, app.tasa_bcv)
        except Exception as e:
            app.mostrar_error(self, e)

class CalculadoraImplicitaScreen(Screen):
    def realizar_calculo(self):
        app = MDApp.get_running_app()
        try:
            tasa_oficial_manual = float(self.ids.tasa_bcv_manual_input.text)
            tasa_no_oficial_manual = float(self.ids.tasa_implicita_input.text)
            
            datos_producto = {
                "costo_fob": float(self.ids.costo_fob_input.text),
                "porcentaje_costo_almacen": float(self.ids.costo_almacen_input.text),
                "tasa_oficial": tasa_oficial_manual,
                "tasa_no_oficial": tasa_no_oficial_manual,
                "porcentaje_gastos": float(self.ids.gastos_input.text),
                "porcentaje_utilidad_neta": float(self.ids.utilidad_input.text),
                "porcentaje_ventas_en_bs": float(self.ids.ventas_bs_input.text)
            }
            if tasa_oficial_manual <= 0 or tasa_no_oficial_manual <= 0:
                raise ValueError("Las tasas deben ser mayores a cero.")
                
            resultados = calcular_precio_simplificado(**datos_producto)
            app.actualizar_labels_resultados(self, resultados, tasa_oficial_manual)
        except Exception as e:
            app.mostrar_error(self, e)

# --- CLASE PRINCIPAL DE LA APLICACIÓN ---
class CalculadoraApp(MDApp):
    dialog = None

    def build(self):
        self.title = "ComparaTasasPro" # <-- Título de la ventana
        self.theme_cls.theme_style = "Dark"
        self.theme_cls.primary_palette = "Blue"
        self.tasa_bcv = 0.0
        self.tasa_no_oficial = 0.0
        threading.Thread(target=self.actualizar_tasas_thread, daemon=True).start()
        return

    def actualizar_tasas_thread(self):
        tasas = obtener_cotizaciones()
        from kivy.clock import Clock
        Clock.schedule_once(lambda dt: self.distribuir_datos_tasas(tasas))

    def distribuir_datos_tasas(self, tasas):
        tasas_screen = self.root.get_screen('tasas')
        fecha_str = f"Tasas para hoy: {datetime.now().strftime('%A, %d de %B de %Y').capitalize()}"
        tasas_screen.ids.status_label.text = fecha_str
        
        lista_de_tasas = tasas_screen.ids.tasas_list
        lista_de_tasas.clear_widgets()

        if tasas:
            icon_map = {"BCV": "bank", "BINANCE": "currency-btc", "PAYPAL": "credit-card-outline", "CÚCUTA": "map-marker-outline", "KONTIGO": "cellphone"}
            default_icon = "currency-usd"
            for nombre, valor in tasas.items():
                if "BCV" in nombre.upper(): self.tasa_bcv = valor
                icon_name = default_icon
                for key, icon in icon_map.items():
                    if key in nombre.upper(): icon_name = icon; break
                item = TwoLineIconListItem(text=f"[b]{nombre}[/b]", secondary_text=f"Bs. {valor:.2f}", theme_text_color="Primary")
                item.add_widget(IconLeftWidget(icon=icon_name, theme_text_color="Primary"))
                lista_de_tasas.add_widget(item)

            tasas_no_oficiales = [v for k, v in tasas.items() if "BCV" not in k.upper()]
            if len(tasas_no_oficiales) >= 3:
                tasas_no_oficiales.sort(); self.tasa_no_oficial = sum(tasas_no_oficiales[1:-1]) / len(tasas_no_oficiales[1:-1])
            elif tasas_no_oficiales: self.tasa_no_oficial = sum(tasas_no_oficiales) / len(tasas_no_oficiales)
            tasa_promedio = sum(tasas.values()) / len(tasas.values())
            
            item_bcv = TwoLineIconListItem(text="[b]Tasa Oficial BCV[/b]", secondary_text=f"Bs. {self.tasa_bcv:.2f}", theme_text_color="Secondary"); item_bcv.add_widget(IconLeftWidget(icon="bank-check", theme_text_color="Secondary")); lista_de_tasas.add_widget(item_bcv)
            item_no_oficial = TwoLineIconListItem(text="[b]Tasa No Oficial (Promedio)[/b]", secondary_text=f"Bs. {self.tasa_no_oficial:.2f}", theme_text_color="Secondary"); item_no_oficial.add_widget(IconLeftWidget(icon="calculator-variant", theme_text_color="Secondary")); lista_de_tasas.add_widget(item_no_oficial)
            item_promedio = TwoLineIconListItem(text="[b]Tasa Promedio General[/b]", secondary_text=f"Bs. {tasa_promedio:.2f}", theme_text_color="Secondary"); item_promedio.add_widget(IconLeftWidget(icon="chart-bar", theme_text_color="Secondary")); lista_de_tasas.add_widget(item_promedio)
            
            self.root.get_screen('calculadora').ids.tasas_card_label.text = f"Oficial BCV: Bs. {self.tasa_bcv:.2f}  |  No Oficial: Bs. {self.tasa_no_oficial:.2f}"
            calc_implicita_screen = self.root.get_screen('calculadora_implicita')
            calc_implicita_screen.ids.tasas_card_label.text = "Tasas a ingresar manualmente"
            calc_implicita_screen.ids.tasa_bcv_manual_input.text = f"{self.tasa_bcv:.2f}"
        else:
            tasas_screen.ids.status_label.text = "Error al obtener tasas."
            self.root.get_screen('calculadora_implicita').ids.tasas_card_label.text = "Modo Offline: ingrese ambas tasas"

    def actualizar_labels_resultados(self, screen, resultados, tasa_bcv):
        screen.ids.cta_label.text = f"Costo Total en Almacén (CTA): ${resultados['costo_total_en_almacen_cta_usd']:.2f}"
        screen.ids.pvm_label.text = f"Precio Venta Mínimo (PVM): ${resultados['precio_venta_minimo_pvm_usd']:.2f}"
        screen.ids.descuento_label.text = f"Descuento Máx. por pago en USD: {resultados['factor_perdida_cambiaria_porcentual']:.2f}%"
        solicitado_por = screen.ids.solicitado_input.text.strip(); producto = screen.ids.producto_input.text.strip()
        screen.ids.solicitado_result_label.text = f"Solicitado por: {solicitado_por}" if solicitado_por else ""
        screen.ids.producto_result_label.text = f"Producto: {producto}" if producto else ""
        fecha_calculo = datetime.now().strftime("%A, %d de %B de %Y - %I:%M %p").capitalize()
        screen.ids.fecha_result_label.text = f"Fecha del Cálculo: {fecha_calculo}"
        screen.ids.bcv_result_label.text = f"TASA OFICIAL (BCV): Bs. {tasa_bcv:.2f}"
        precio_usd = resultados['precio_venta_final_ajustado_pvd_usd']
        screen.ids.pvp_label.text = f"PVP USD: ${precio_usd:,.2f}"
        precio_bs = precio_usd * tasa_bcv
        precio_bs_formateado = locale.format_string("%.2f", precio_bs, grouping=True)
        screen.ids.pvp_bs_label.text = f"PVP Bs.: {precio_bs_formateado}"

    def mostrar_error(self, screen, e):
        screen.ids.pvp_label.text = f"Error: {e}"
        screen.ids.pvp_bs_label.text = ""

    def show_about_dialog(self):
        if not self.dialog:
            self.dialog = MDDialog(
                title="ComparaTasasPro v1.0", # <-- Nuevo nombre
                text="[b]Descripción:[/b]\n"
                     "Herramienta de análisis para estimar el precio de venta final (PVP) de productos, ajustado para cubrir costos, gastos, utilidad y el diferencial cambiario.\n\n"
                     "[b]Desarrollado por:[/b]\n"
                     "Melvin E. Padilla\n\n"
                     "[b]Contacto:[/b]\n"
                     "Instagram: @pydatacrunch\n"
                     "Email: ingenieria.vnz@gmail.com\n\n"
                     "[b]Agradecimientos:[/b]\n"
                     "Tasas obtenidas de kaskogo.online.",
                buttons=[
                    MDFlatButton(
                        text="CERRAR",
                        theme_text_color="Custom",
                        text_color=self.theme_cls.primary_color,
                        on_release=lambda x: self.dialog.dismiss(),
                    ),
                ],
            )
        self.dialog.open()

if __name__ == '__main__':
    try:
        locale.setlocale(locale.LC_ALL, 'es_ES.UTF-8')
    except locale.Error:
        try: locale.setlocale(locale.LC_ALL, 'Spanish')
        except locale.Error: print("Advertencia: No se pudo establecer el 'locale' a español.")
    
    CalculadoraApp().run()
