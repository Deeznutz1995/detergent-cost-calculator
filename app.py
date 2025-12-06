import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go

st.set_page_config(page_title="Detergent Cost Calculator", layout="wide")
st.title("🧼 Detergent Powder Cost Modeling Calculator")

# ============================================================================
# CALCULATION FUNCTIONS
# ============================================================================

def validate_recipe(ingredients):
    """Check if recipe percentages sum to 100"""
    total = sum([ing['percent'] for ing in ingredients])
    return abs(total - 100.0) <= 0.01, total

def calculate_costs(inputs):
    """Main calculation engine"""
    results = {}
    
    # Extract inputs
    unit_weight_g = inputs['unit_weight_g']
    units_to_produce = inputs['units_to_produce']
    exchange_rate = inputs['exchange_rate']
    ingredients = inputs['ingredients']
    prices = inputs['prices']
    packaging = inputs['packaging']
    logistics = inputs['logistics']
    sales = inputs['sales']
    
    # Validate recipe
    is_valid, total_pct = validate_recipe(ingredients)
    if not is_valid:
        return None, f"Recipe percentages sum to {total_pct:.2f}%, must be 100%"
    
    # ===== INGREDIENTS =====
    total_grams = unit_weight_g * units_to_produce
    ingredients_detail = []
    total_ingredient_cost_usd = 0
    
    for ing in ingredients:
        name = ing['name']
        percent = ing['percent']
        price_per_kg = prices.get(name, 0)
        
        ing_grams = total_grams * (percent / 100)
        ing_kg = ing_grams / 1000
        ing_cost_usd = ing_kg * price_per_kg
        ing_cost_gnf = ing_cost_usd * exchange_rate
        
        ingredients_detail.append({
            'name': name,
            'percent': percent,
            'grams': ing_grams,
            'kg': ing_kg,
            'price_per_kg': price_per_kg,
            'cost_usd': ing_cost_usd,
            'cost_gnf': ing_cost_gnf
        })
        total_ingredient_cost_usd += ing_cost_usd
    
    results['ingredients'] = ingredients_detail
    results['total_ingredient_cost_usd'] = total_ingredient_cost_usd
    
    # ===== PACKAGING =====
    film_yield = packaging['yield_pouches_per_kg']
    film_total_kg = units_to_produce / film_yield if film_yield > 0 else 0
    film_price_per_kg = packaging['price_per_kg']
    film_cost_usd = film_total_kg * film_price_per_kg
    film_cost_gnf = film_cost_usd * exchange_rate
    
    # Printing setup amortization
    printing_setup = packaging['printing_setup_usd']
    amortized_setup = printing_setup  # amortize over one run for now
    
    results['packaging'] = {
        'film_total_kg': film_total_kg,
        'film_cost_usd': film_cost_usd,
        'film_cost_gnf': film_cost_gnf,
        'amortized_setup_usd': amortized_setup
    }
    
    # ===== LANDED COST =====
    goods_value_usd = total_ingredient_cost_usd + film_cost_usd
    customs_duties_usd = goods_value_usd * (logistics['customs_percent'] / 100)
    
    landed_cost_usd = (goods_value_usd + customs_duties_usd + 
                       logistics['freight_usd'] + logistics['clearing_usd'] + 
                       logistics['inland_transport_usd'])
    
    results['landed_cost'] = {
        'goods_value_usd': goods_value_usd,
        'customs_duties_usd': customs_duties_usd,
        'freight_usd': logistics['freight_usd'],
        'clearing_usd': logistics['clearing_usd'],
        'inland_transport_usd': logistics['inland_transport_usd'],
        'landed_cost_usd': landed_cost_usd
    }
    
    # ===== PRODUCTION OVERHEAD =====
    packaging_conversion_total = logistics['packaging_conversion_per_pouch_usd'] * units_to_produce
    production_overhead_usd = (logistics['labor_usd'] + 
                              logistics['other_overhead_usd'] + 
                              packaging_conversion_total + 
                              amortized_setup)
    
    results['overhead'] = {
        'labor_usd': logistics['labor_usd'],
        'packaging_conversion_usd': packaging_conversion_total,
        'other_overhead_usd': logistics['other_overhead_usd'],
        'amortized_setup_usd': amortized_setup,
        'total_usd': production_overhead_usd
    }
    
    # ===== TOTAL COST & CPU =====
    total_cost_usd = landed_cost_usd + production_overhead_usd
    cpu_usd = total_cost_usd / units_to_produce if units_to_produce > 0 else 0
    cpu_gnf = cpu_usd * exchange_rate
    
    results['cost_summary'] = {
        'total_cost_usd': total_cost_usd,
        'cpu_usd': cpu_usd,
        'cpu_gnf': cpu_gnf
    }
    
    # ===== PRICING & MARGINS =====
    target_margin = sales['manufacturer_margin_percent']
    manufacturer_price_usd = cpu_usd * (1 + target_margin / 100)
    
    retail_price_gnf = sales['retail_price_gnf']
    retail_price_usd = retail_price_gnf / exchange_rate if exchange_rate > 0 else 0
    
    gross_margin_usd = retail_price_usd - cpu_usd
    gross_margin_pct = (gross_margin_usd / retail_price_usd * 100) if retail_price_usd > 0 else 0
    
    results['pricing'] = {
        'cpu_usd': cpu_usd,
        'cpu_gnf': cpu_gnf,
        'manufacturer_price_usd': manufacturer_price_usd,
        'retail_price_usd': retail_price_usd,
        'retail_price_gnf': retail_price_gnf,
        'gross_margin_usd': gross_margin_usd,
        'gross_margin_pct': gross_margin_pct
    }
    
    return results, None

# ============================================================================
# STREAMLIT UI
# ============================================================================

# Initialize session state with defaults
if 'inputs' not in st.session_state:
    st.session_state.inputs = {
        'unit_weight_g': 25,
        'units_to_produce': 10000,
        'exchange_rate': 1200.0,
        'ingredients': [
            {'name': 'Soda_ash', 'percent': 70.68},
            {'name': 'SLES', 'percent': 20.0},
            {'name': 'Water', 'percent': 1.0},
            {'name': 'Glycerine', 'percent': 2.0},
            {'name': 'Silicate', 'percent': 5.0},
            {'name': 'Color', 'percent': 0.3},
            {'name': 'Fragrance', 'percent': 1.0},
            {'name': 'Optical_brightener', 'percent': 0.01}
        ],
        'prices': {
            'Soda_ash': 0.40, 'SLES': 1.00, 'Water': 0.0,
            'Glycerine': 1.50, 'Silicate': 0.60, 'Color': 20.0,
            'Fragrance': 15.0, 'Optical_brightener': 10.0
        },
        'packaging': {
            'price_per_kg': 3.03,
            'yield_pouches_per_kg': 285.71,
            'printing_setup_usd': 420.0
        },
        'logistics': {
            'customs_percent': 10.0,
            'freight_usd': 1000.0,
            'clearing_usd': 200.0,
            'inland_transport_usd': 300.0,
            'labor_usd': 200.0,
            'packaging_conversion_per_pouch_usd': 0.01,
            'other_overhead_usd': 100.0
        },
        'sales': {
            'manufacturer_margin_percent': 30.0,
            'retail_price_gnf': 1000.0
        }
    }

# Sidebar inputs
with st.sidebar:
    st.header("⚙️ Configuration")
    
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("SKU")
        unit_weight = st.number_input("Unit Weight (g)", min_value=1, value=st.session_state.inputs['unit_weight_g'], step=1)
        units_prod = st.number_input("Units to Produce", min_value=1, value=st.session_state.inputs['units_to_produce'], step=1000)
    
    with col2:
        st.subheader("Exchange")
        exch_rate = st.number_input("USD to GNF", min_value=1.0, value=st.session_state.inputs['exchange_rate'], step=10.0)
        customs = st.number_input("Customs %", min_value=0.0, value=st.session_state.inputs['logistics']['customs_percent'], step=1.0)
    
    st.subheader("Ingredient Prices (USD/kg)")
    for ing in st.session_state.inputs['ingredients']:
        ing_name = ing['name']
        current_price = st.session_state.inputs['prices'].get(ing_name, 0.0)
        new_price = st.number_input(f"{ing_name}", min_value=0.0, value=current_price, step=0.1)
        st.session_state.inputs['prices'][ing_name] = new_price
    
    st.subheader("Packaging")
    film_price = st.number_input("Film Price (USD/kg)", min_value=0.0, value=st.session_state.inputs['packaging']['price_per_kg'], step=0.1)
    film_yield = st.number_input("Film Yield (pouches/kg)", min_value=1.0, value=st.session_state.inputs['packaging']['yield_pouches_per_kg'], step=1.0)
    printing = st.number_input("Printing Setup (USD)", min_value=0.0, value=st.session_state.inputs['packaging']['printing_setup_usd'], step=10.0)
    
    st.subheader("Logistics")
    freight = st.number_input("Freight (USD)", min_value=0.0, value=st.session_state.inputs['logistics']['freight_usd'], step=100.0)
    clearing = st.number_input("Clearing (USD)", min_value=0.0, value=st.session_state.inputs['logistics']['clearing_usd'], step=10.0)
    inland = st.number_input("Inland Transport (USD)", min_value=0.0, value=st.session_state.inputs['logistics']['inland_transport_usd'], step=10.0)
    labor = st.number_input("Labor (USD)", min_value=0.0, value=st.session_state.inputs['logistics']['labor_usd'], step=10.0)
    pkg_conv = st.number_input("Pkg Conversion (USD/pouch)", min_value=0.0, value=st.session_state.inputs['logistics']['packaging_conversion_per_pouch_usd'], step=0.001)
    overhead = st.number_input("Other Overhead (USD)", min_value=0.0, value=st.session_state.inputs['logistics']['other_overhead_usd'], step=10.0)
    
    st.subheader("Sales")
    margin_pct = st.number_input("Target Margin %", min_value=0.0, value=st.session_state.inputs['sales']['manufacturer_margin_percent'], step=1.0)
    retail_price = st.number_input("Retail Price (GNF)", min_value=0.0, value=st.session_state.inputs['sales']['retail_price_gnf'], step=100.0)

# Update session state
st.session_state.inputs['unit_weight_g'] = unit_weight
st.session_state.inputs['units_to_produce'] = units_prod
st.session_state.inputs['exchange_rate'] = exch_rate
st.session_state.inputs['logistics']['customs_percent'] = customs
st.session_state.inputs['packaging']['price_per_kg'] = film_price
st.session_state.inputs['packaging']['yield_pouches_per_kg'] = film_yield
st.session_state.inputs['packaging']['printing_setup_usd'] = printing
st.session_state.inputs['logistics']['freight_usd'] = freight
st.session_state.inputs['logistics']['clearing_usd'] = clearing
st.session_state.inputs['logistics']['inland_transport_usd'] = inland
st.session_state.inputs['logistics']['labor_usd'] = labor
st.session_state.inputs['logistics']['packaging_conversion_per_pouch_usd'] = pkg_conv
st.session_state.inputs['logistics']['other_overhead_usd'] = overhead
st.session_state.inputs['sales']['manufacturer_margin_percent'] = margin_pct
st.session_state.inputs['sales']['retail_price_gnf'] = retail_price

# Run calculation
results, error = calculate_costs(st.session_state.inputs)

if error:
    st.error(f"❌ {error}")
else:
    st.success("✅ Calculation complete!")
    
    # KPI Row
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("CPU (USD)", f"${results['cost_summary']['cpu_usd']:.4f}")
    with col2:
        st.metric("CPU (GNF)", f"{results['cost_summary']['cpu_gnf']:.0f}")
    with col3:
        st.metric("Total Cost", f"${results['cost_summary']['total_cost_usd']:.2f}")
    with col4:
        st.metric("Margin %", f"{results['pricing']['gross_margin_pct']:.1f}%")
    
    # Tabs
    tab1, tab2, tab3 = st.tabs(["Cost Breakdown", "Ingredients", "Pricing"])
    
    with tab1:
        st.subheader("Cost Breakdown (USD)")
        cost_breakdown = [
            ['Ingredients', results['landed_cost']['goods_value_usd']],
            ['Film', results['packaging']['film_cost_usd']],
            ['Customs & Duties', results['landed_cost']['customs_duties_usd']],
            ['Freight', results['landed_cost']['freight_usd']],
            ['Clearing', results['landed_cost']['clearing_usd']],
            ['Inland Transport', results['landed_cost']['inland_transport_usd']],
            ['Landed Cost', results['landed_cost']['landed_cost_usd']],
            ['Labor', results['overhead']['labor_usd']],
            ['Packaging Conversion', results['overhead']['packaging_conversion_usd']],
            ['Printing Setup', results['overhead']['amortized_setup_usd']],
            ['Other Overhead', results['overhead']['other_overhead_usd']],
            ['TOTAL COST', results['cost_summary']['total_cost_usd']]
        ]
        df_breakdown = pd.DataFrame(cost_breakdown, columns=['Item', 'USD'])
        st.dataframe(df_breakdown, use_container_width=True)
        
        fig = px.bar(df_breakdown[:-1], x='Item', y='USD', title='Cost Breakdown by Category')
        st.plotly_chart(fig, use_container_width=True)
    
    with tab2:
        st.subheader("Ingredient Details")
        df_ing = pd.DataFrame(results['ingredients'])
        st.dataframe(df_ing[['name', 'percent', 'kg', 'price_per_kg', 'cost_usd']], use_container_width=True)
        
        fig_pie = px.pie(df_ing, values='cost_usd', names='name', title='Ingredient Cost %')
        st.plotly_chart(fig_pie, use_container_width=True)
    
    with tab3:
        st.subheader("Pricing & Margins")
        pricing_data = [
            ['CPU (USD)', f"${results['pricing']['cpu_usd']:.4f}"],
            ['CPU (GNF)', f"{results['pricing']['cpu_gnf']:.0f}"],
            ['Manufacturer Price (USD)', f"${results['pricing']['manufacturer_price_usd']:.4f}"],
            ['Retail Price (USD)', f"${results['pricing']['retail_price_usd']:.4f}"],
            ['Retail Price (GNF)', f"{results['pricing']['retail_price_gnf']:.0f}"],
            ['Gross Margin (USD)', f"${results['pricing']['gross_margin_usd']:.4f}"],
            ['Gross Margin %', f"{results['pricing']['gross_margin_pct']:.2f}%"]
        ]
        df_pricing = pd.DataFrame(pricing_data, columns=['Item', 'Value'])
        st.dataframe(df_pricing, use_container_width=True)
    
    # Export
    st.subheader("📥 Export")
    csv_buffer = io.StringIO()
    csv_buffer.write("DETERGENT COST MODEL\n")
    csv_buffer.write(f"Units Produced: {st.session_state.inputs['units_to_produce']}\n")
    csv_buffer.write(f"CPU (USD): ${results['cost_summary']['cpu_usd']:.4f}\n")
    csv_buffer.write(f"CPU (GNF): {results['cost_summary']['cpu_gnf']:.0f}\n\n")
    csv_buffer.write("INGREDIENTS\n")
    df_ing.to_csv(csv_buffer, index=False)
    
    import io
    st.download_button(
        label="Download CSV",
        data=csv_buffer.getvalue(),
        file_name="detergent_cost_model.csv",
        mime="text/csv"
    )
