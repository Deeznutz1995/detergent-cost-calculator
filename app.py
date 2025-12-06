import streamlit as st
import pandas as pd
import numpy as np
import json
from datetime import datetime
import io
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
import plotly.express as px
import plotly.graph_objects as go

# ============================================================================
# CORE CALCULATION ENGINE
# ============================================================================

class DetergentCostCalculator:
    def __init__(self, inputs):
        self.inputs = inputs
        self.results = {}
        self.validation_errors = []
        
    def validate(self):
        """Validate all inputs"""
        errors = []
        
        # Check recipe percentages sum to 100 ± 0.01
        recipe = self.inputs.get('recipe', {})
        total_percent = sum([ing.get('percent', 0) for ing in recipe.get('ingredients', [])])
        if abs(total_percent - 100.0) > 0.01:
            errors.append(f"Recipe percentages sum to {total_percent}%, must be 100% ± 0.01%")
        
        # Check positive values
        if self.inputs.get('sku', {}).get('unit_weight_g', 0) <= 0:
            errors.append("Unit weight must be > 0")
        if self.inputs.get('sku', {}).get('units_to_produce', 0) <= 0:
            errors.append("Units to produce must be > 0")
        
        # Check ingredient prices
        for ing_name, price in self.inputs.get('ingredient_prices', {}).items():
            if price < 0:
                errors.append(f"Ingredient price for {ing_name} cannot be negative")
        
        self.validation_errors = errors
        return len(errors) == 0
    
    def calculate(self):
        """Run all calculations"""
        if not self.validate():
            return False
        
        sku = self.inputs['sku']
        recipe = self.inputs['recipe']
        unit_weight_g = sku['unit_weight_g']
        units_to_produce = sku['units_to_produce']
        
        # ===== INGREDIENTS =====
        total_grams = unit_weight_g * units_to_produce
        ingredients_detail = []
        total_ingredient_cost_usd = 0
        
        for ing in recipe['ingredients']:
            ing_name = ing['name']
            percent = ing['percent']
            price_per_kg = self.inputs['ingredient_prices'].get(ing_name, 0)
            
            ing_grams = total_grams * (percent / 100)
            ing_kg = ing_grams / 1000
            ing_cost_usd = ing_kg * price_per_kg
            ing_cost_gnf = ing_cost_usd * self.inputs['exchange_rate']
            
            ingredients_detail.append({
                'name': ing_name,
                'percent': percent,
                'grams': ing_grams,
                'kg': ing_kg,
                'price_per_kg': price_per_kg,
                'cost_usd': ing_cost_usd,
                'cost_gnf': ing_cost_gnf
            })
            total_ingredient_cost_usd += ing_cost_usd
        
        self.results['ingredients'] = ingredients_detail
        self.results['total_ingredient_cost_usd'] = total_ingredient_cost_usd
        
        # ===== PACKAGING =====
        packaging = self.inputs['packaging']
        film_yield_pouches_per_kg = packaging['yield_pouches_per_kg']
        film_total_kg = units_to_produce / film_yield_pouches_per_kg
        
        # Enforce MOQ
        film_price_per_kg = packaging['price_per_kg']
        moq_kg = packaging['moq_kg']
        if film_total_kg < moq_kg:
            film_total_kg_ordered = moq_kg
            self.results['film_moq_warning'] = f"Film MOQ is {moq_kg}kg; need {film_total_kg:.2f}kg; ordering {moq_kg}kg"
        else:
            film_total_kg_ordered = film_total_kg
            self.results['film_moq_warning'] = None
        
        film_cost_usd = film_total_kg_ordered * film_price_per_kg
        film_cost_gnf = film_cost_usd * self.inputs['exchange_rate']
        
        # Printing setup amortization
        printing_setup_usd = packaging['printing_setup_usd']
        amortization_units = self.inputs.get('amortization_units', units_to_produce)
        amortized_setup_per_run = printing_setup_usd / amortization_units * units_to_produce if amortization_units > 0 else 0
        
        self.results['packaging'] = {
            'film_total_kg_needed': film_total_kg,
            'film_total_kg_ordered': film_total_kg_ordered,
            'film_cost_usd': film_cost_usd,
            'film_cost_gnf': film_cost_gnf,
            'amortized_setup_usd': amortized_setup_per_run
        }
        
        # ===== LANDED COST =====
        goods_value_usd = total_ingredient_cost_usd + film_cost_usd
        customs_duties_usd = goods_value_usd * (self.inputs['customs_percent'] / 100)
        
        logistics = self.inputs['logistics']
        landed_cost_usd = (goods_value_usd + customs_duties_usd + 
                          logistics['freight_usd'] + logistics['clearing_usd'] + 
                          logistics['inland_transport_usd'] + 
                          logistics.get('demurrage_usd', 0))
        
        self.results['landed_cost_detail'] = {
            'goods_value_usd': goods_value_usd,
            'customs_duties_usd': customs_duties_usd,
            'freight_usd': logistics['freight_usd'],
            'clearing_usd': logistics['clearing_usd'],
            'inland_transport_usd': logistics['inland_transport_usd'],
            'demurrage_usd': logistics.get('demurrage_usd', 0),
            'landed_cost_usd': landed_cost_usd
        }
        
        # ===== PRODUCTION OVERHEAD =====
        packaging_conversion_total = logistics.get('packaging_conversion_per_pouch_usd', 0) * units_to_produce
        production_overhead_usd = (logistics.get('labor_usd', 0) + 
                                 logistics.get('other_overhead_usd', 0) + 
                                 packaging_conversion_total + 
                                 amortized_setup_per_run)
        
        self.results['production_overhead'] = {
            'labor_usd': logistics.get('labor_usd', 0),
            'other_overhead_usd': logistics.get('other_overhead_usd', 0),
            'packaging_conversion_total_usd': packaging_conversion_total,
            'amortized_setup_usd': amortized_setup_per_run,
            'total_usd': production_overhead_usd
        }
        
        # ===== TOTAL COST & CPU =====
        total_cost_usd = landed_cost_usd + production_overhead_usd
        cpu_usd = total_cost_usd / units_to_produce if units_to_produce > 0 else 0
        cpu_gnf = cpu_usd * self.inputs['exchange_rate']
        
        self.results['cost_summary'] = {
            'total_cost_usd': total_cost_usd,
            'cpu_usd': cpu_usd,
            'cpu_gnf': cpu_gnf
        }
        
        # ===== PRICING & MARGINS =====
        sales = self.inputs['sales']
        target_margin_pct = sales.get('manufacturer_margin_percent', 30)
        manufacturer_price_usd = cpu_usd * (1 + target_margin_pct / 100)
        manufacturer_price_gnf = manufacturer_price_usd * self.inputs['exchange_rate']
        
        retail_price_gnf = sales.get('retail_price_gnf', 1000)
        retail_price_usd = retail_price_gnf / self.inputs['exchange_rate']
        
        gross_margin_usd = retail_price_usd - cpu_usd
        gross_margin_pct = (gross_margin_usd / retail_price_usd * 100) if retail_price_usd > 0 else 0
        
        self.results['pricing'] = {
            'cpu_usd': cpu_usd,
            'cpu_gnf': cpu_gnf,
            'manufacturer_price_usd': manufacturer_price_usd,
            'manufacturer_price_gnf': manufacturer_price_gnf,
            'retail_price_usd': retail_price_usd,
            'retail_price_gnf': retail_price_gnf,
            'gross_margin_usd': gross_margin_usd,
            'gross_margin_pct': gross_margin_pct
        }
        
        # ===== BREAKEVEN =====
        fixed_costs = amortized_setup_per_run + logistics.get('labor_usd', 0)
        variable_cost_per_unit = cpu_usd - (fixed_costs / units_to_produce if units_to_produce > 0 else 0)
        breakeven_units = fixed_costs / (manufacturer_price_usd - variable_cost_per_unit) if (manufacturer_price_usd - variable_cost_per_unit) > 0 else float('inf')
        
        self.results['breakeven'] = {
            'fixed_costs_usd': fixed_costs,
            'variable_cost_per_unit_usd': variable_cost_per_unit,
            'breakeven_units': int(breakeven_units)
        }
        
        return True

# ============================================================================
# STREAMLIT UI
# ============================================================================

st.set_page_config(page_title="Detergent Cost Calculator", layout="wide")
st.title("🧼 Detergent Powder Cost Modeling Calculator")

# Initialize session state
if 'inputs' not in st.session_state:
    st.session_state.inputs = {
        'project_name': 'Sample Detergent Project',
        'exchange_rate': 1200,
        'customs_percent': 10,
        'amortization_units': 10000,
        'sku': {'sku_name': '25g_pouch', 'unit_weight_g': 25, 'units_to_produce': 10000},
        'recipe': {
            'ingredients': [
                {'name': 'Soda_ash', 'percent': 70.68},
                {'name': 'SLES', 'percent': 20.0},
                {'name': 'Water', 'percent': 1.0},
                {'name': 'Glycerine', 'percent': 2.0},
                {'name': 'Silicate', 'percent': 5.0},
                {'name': 'Color', 'percent': 0.3},
                {'name': 'Fragrance', 'percent': 1.0},
                {'name': 'Optical_brightener', 'percent': 0.01}
            ]
        },
        'ingredient_prices': {
            'Soda_ash': 0.40, 'SLES': 1.00, 'Water': 0.0,
            'Glycerine': 1.50, 'Silicate': 0.60, 'Color': 20.0,
            'Fragrance': 15.0, 'Optical_brightener': 10.0
        },
        'packaging': {
            'price_per_kg': 3.03, 'moq_kg': 350, 'yield_pouches_per_kg': 285.71,
            'printing_setup_usd': 420
        },
        'logistics': {
            'freight_usd': 1000, 'clearing_usd': 200, 'inland_transport_usd': 300,
            'labor_usd': 200, 'packaging_conversion_per_pouch_usd': 0.01,
            'other_overhead_usd': 100, 'demurrage_usd': 0
        },
        'sales': {
            'manufacturer_margin_percent': 30,
            'retail_price_gnf': 1000
        }
    }

# Left panel: Inputs
with st.sidebar:
    st.header("⚙️ Inputs")
    
    project_name = st.text_input("Project Name", st.session_state.inputs['project_name'])
    st.session_state.inputs['project_name'] = project_name
    
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("SKU")
        sku_name = st.text_input("SKU Name", st.session_state.inputs['sku']['sku_name'])
        unit_weight = st.number_input("Unit Weight (g)", min_value=1, value=int(st.session_state.inputs['sku']['unit_weight_g']))
        units_prod = st.number_input("Units to Produce", min_value=1, value=int(st.session_state.inputs['sku']['units_to_produce']))
        st.session_state.inputs['sku'] = {'sku_name': sku_name, 'unit_weight_g': unit_weight, 'units_to_produce': units_prod}
    
    with col2:
        st.subheader("Exchange Rate & Customs")
        exchange_rate = st.number_input("USD to GNF Rate", value=st.session_state.inputs['exchange_rate'], min_value=1.0)
        customs_pct = st.number_input("Customs %", value=st.session_state.inputs['customs_percent'], min_value=0.0)
        st.session_state.inputs['exchange_rate'] = exchange_rate
        st.session_state.inputs['customs_percent'] = customs_pct
    
    st.subheader("Recipe Ingredients")
    for i, ing in enumerate(st.session_state.inputs['recipe']['ingredients']):
        col_name, col_pct, col_price = st.columns([2, 1, 1.5])
        with col_name:
            ing_name = st.text_input(f"Ingredient {i+1}", ing['name'], key=f"ing_name_{i}")
        with col_pct:
            ing_pct = st.number_input(f"% {i+1}", value=ing['percent'], key=f"ing_pct_{i}")
        with col_price:
            ing_price = st.number_input(f"$/kg {i+1}", value=st.session_state.inputs['ingredient_prices'].get(ing_name, 0.0), key=f"ing_price_{i}")
        
        st.session_state.inputs['recipe']['ingredients'][i]['name'] = ing_name
        st.session_state.inputs['recipe']['ingredients'][i]['percent'] = ing_pct
        st.session_state.inputs['ingredient_prices'][ing_name] = ing_price
    
    st.subheader("Packaging")
    film_price = st.number_input("Film Price (USD/kg)", value=st.session_state.inputs['packaging']['price_per_kg'])
    moq_kg = st.number_input("Film MOQ (kg)", value=st.session_state.inputs['packaging']['moq_kg'])
    yield_pouches = st.number_input("Yield (pouches/kg)", value=st.session_state.inputs['packaging']['yield_pouches_per_kg'])
    printing_setup = st.number_input("Printing Setup (USD)", value=st.session_state.inputs['packaging']['printing_setup_usd'])
    st.session_state.inputs['packaging'] = {
        'price_per_kg': film_price, 'moq_kg': moq_kg,
        'yield_pouches_per_kg': yield_pouches, 'printing_setup_usd': printing_setup
    }
    
    st.subheader("Logistics & Overhead")
    freight = st.number_input("Freight (USD)", value=st.session_state.inputs['logistics']['freight_usd'])
    clearing = st.number_input("Clearing (USD)", value=st.session_state.inputs['logistics']['clearing_usd'])
    inland = st.number_input("Inland Transport (USD)", value=st.session_state.inputs['logistics']['inland_transport_usd'])
    labor = st.number_input("Labor (USD)", value=st.session_state.inputs['logistics']['labor_usd'])
    pkg_conv = st.number_input("Packaging Conversion (USD/pouch)", value=st.session_state.inputs['logistics']['packaging_conversion_per_pouch_usd'])
    overhead = st.number_input("Other Overhead (USD)", value=st.session_state.inputs['logistics']['other_overhead_usd'])
    st.session_state.inputs['logistics'] = {
        'freight_usd': freight, 'clearing_usd': clearing, 'inland_transport_usd': inland,
        'labor_usd': labor, 'packaging_conversion_per_pouch_usd': pkg_conv,
        'other_overhead_usd': overhead, 'demurrage_usd': 0
    }
    
    st.subheader("Sales")
    margin_pct = st.number_input("Target Margin %", value=st.session_state.inputs['sales']['manufacturer_margin_percent'])
    retail_gnf = st.number_input("Retail Price (GNF)", value=st.session_state.inputs['sales']['retail_price_gnf'])
    st.session_state.inputs['sales'] = {
        'manufacturer_margin_percent': margin_pct,
        'retail_price_gnf': retail_gnf
    }

# Run calculation
calc = DetergentCostCalculator(st.session_state.inputs)
success = calc.calculate()

if not success:
    st.error("❌ Validation Errors:")
    for err in calc.validation_errors:
        st.error(f"  • {err}")
else:
    # Main content area
    st.success("✅ Calculation complete!")
    
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("CPU (USD)", f"${calc.results['cost_summary']['cpu_usd']:.4f}")
    with col2:
        st.metric("CPU (GNF)", f"{calc.results['cost_summary']['cpu_gnf']:.0f}")
    with col3:
        st.metric("Total Cost (USD)", f"${calc.results['cost_summary']['total_cost_usd']:.2f}")
    with col4:
        st.metric("Margin %", f"{calc.results['pricing']['gross_margin_pct']:.1f}%")
    
    # Tabs for different views
    tab1, tab2, tab3, tab4 = st.tabs(["Cost Breakdown", "Ingredients", "Pricing & Margins", "Sensitivity"])
    
    with tab1:
        st.subheader("Cost Breakdown")
        cost_data = []
        landing = calc.results['landed_cost_detail']
        cost_data.append(['Goods Value (Ingredients)', landing['goods_value_usd']])
        cost_data.append(['Customs & Duties', landing['customs_duties_usd']])
        cost_data.append(['Freight', landing['freight_usd']])
        cost_data.append(['Clearing', landing['clearing_usd']])
        cost_data.append(['Inland Transport', landing['inland_transport_usd']])
        cost_data.append(['Landed Cost', landing['landed_cost_usd']])
        
        prod_oh = calc.results['production_overhead']
        cost_data.append(['Labor', prod_oh['labor_usd']])
        cost_data.append(['Packaging Conversion', prod_oh['packaging_conversion_total_usd']])
        cost_data.append(['Printing Setup (Amortized)', prod_oh['amortized_setup_usd']])
        cost_data.append(['Other Overhead', prod_oh['other_overhead_usd']])
        cost_data.append(['Total Cost', calc.results['cost_summary']['total_cost_usd']])
        
        df_cost = pd.DataFrame(cost_data, columns=['Item', 'USD'])
        st.table(df_cost)
        
        fig_cost = px.bar(df_cost[:-1], x='Item', y='USD', title='Cost Breakdown by Category',
                         labels={'USD': 'Cost (USD)'})
        st.plotly_chart(fig_cost, use_container_width=True)
    
    with tab2:
        st.subheader("Ingredient Details")
        df_ing = pd.DataFrame(calc.results['ingredients'])
        st.dataframe(df_ing[['name', 'percent', 'kg', 'price_per_kg', 'cost_usd', 'cost_gnf']], use_container_width=True)
        
        fig_ing = px.pie(df_ing, values='cost_usd', names='name', title='Ingredient Cost Distribution')
        st.plotly_chart(fig_ing, use_container_width=True)
    
    with tab3:
        st.subheader("Pricing & Margins")
        pricing_data = [
            ['CPU (USD)', calc.results['pricing']['cpu_usd']],
            ['CPU (GNF)', calc.results['pricing']['cpu_gnf']],
            ['Manufacturer Price (USD)', calc.results['pricing']['manufacturer_price_usd']],
            ['Manufacturer Price (GNF)', calc.results['pricing']['manufacturer_price_gnf']],
            ['Retail Price (USD)', calc.results['pricing']['retail_price_usd']],
            ['Retail Price (GNF)', calc.results['pricing']['retail_price_gnf']],
            ['Gross Margin (USD)', calc.results['pricing']['gross_margin_usd']],
            ['Margin %', f"{calc.results['pricing']['gross_margin_pct']:.2f}%"]
        ]
        df_pricing = pd.DataFrame(pricing_data, columns=['Item', 'Value'])
        st.table(df_pricing)
        
        st.subheader("Breakeven Analysis")
        be = calc.results['breakeven']
        st.metric("Breakeven Units", f"{be['breakeven_units']:,}")
        st.write(f"Fixed Costs: ${be['fixed_costs_usd']:.2f}")
    
    with tab4:
        st.subheader("Sensitivity Analysis")
        st.write("Adjust key inputs to see CPU impact:")
        
        col_s1, col_s2, col_s3 = st.columns(3)
        with col_s1:
            sles_var = st.slider("SLES Price Variance (%)", -30, 30, 0)
        with col_s2:
            film_var = st.slider("Film Price Variance (%)", -30, 30, 0)
        with col_s3:
            freight_var = st.slider("Freight Variance (%)", -30, 30, 0)
        
        # Recalculate with variances
        scenarios = []
        for sles_pct in [-20, -10, 0, 10, 20]:
            inputs_var = json.loads(json.dumps(st.session_state.inputs))
            inputs_var['ingredient_prices']['SLES'] *= (1 + sles_pct / 100)
            calc_var = DetergentCostCalculator(inputs_var)
            calc_var.calculate()
            scenarios.append({'SLES_var': sles_pct, 'CPU': calc_var.results['cost_summary']['cpu_usd']})
        
        df_sens = pd.DataFrame(scenarios)
        fig_sens = px.line(df_sens, x='SLES_var', y='CPU', title='CPU Sensitivity to SLES Price', markers=True)
        st.plotly_chart(fig_sens, use_container_width=True)
    
    # Export buttons
    st.subheader("📊 Export & Reports")
    col_exp1, col_exp2 = st.columns(2)
    
    with col_exp1:
        # CSV Export
        csv_data = io.StringIO()
        csv_data.write("DETERGENT POWDER COST MODEL EXPORT\n")
        csv_data.write(f"Project: {st.session_state.inputs['project_name']}\n")
        csv_data.write(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        csv_data.write("INGREDIENTS\n")
        df_ing.to_csv(csv_data, index=False)
        csv_data.write("\n\nCOST SUMMARY\n")
        df_cost.to_csv(csv_data, index=False)
        
        st.download_button(
            label="⬇️ Download CSV",
            data=csv_data.getvalue(),
            file_name=f"{st.session_state.inputs['project_name']}_cost_model.csv",
            mime="text/csv"
        )
    
    with col_exp2:
        st.write("📋 PDF Report: Create manual export via Print → Save as PDF")
