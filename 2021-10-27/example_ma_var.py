"""
VAR Analysis with Massachusetts Cannabis Data
Cannabis Data Science

Authors: Keegan Skeate <keegan@cannlytics.com>
Created: 10/27/2021
Updated: 10/27/2021
License: MIT License <https://opensource.org/licenses/MIT>

Objective:
    
    1. Forecast cannabis sales in Massachusetts for the remainder of the year
    using various economic models.
    
    2. Visualize and save the forecasts.
    
    3. Compare the forecasts with actual data in the future.

Data Sources:

    MA Cannabis Control Commission
    - Average Monthly Price per Ounce for Adult-Use Cannabis: https://dev.socrata.com/foundry/opendata.mass-cannabis-control.com/rqtv-uenj
    - Plant Activity and Volume: https://dev.socrata.com/foundry/opendata.mass-cannabis-control.com/j3q7-3usu

    Fed Fred
    - Federal funds interest rate: https://fred.stlouisfed.org/series/FEDFUNDS

"""
# External imports
from dotenv import dotenv_values
from fredapi import Fred
import numpy as np
import pandas as pd
import requests
from statsmodels.tsa.api import VAR

# Internal imports
from utils import end_of_period_timeseries, reverse_dataframe

#--------------------------------------------------------------------------
# Get MA public cannabis data.
#--------------------------------------------------------------------------

# Setup Socrata API, get the App Token, and define the headers.
config = dotenv_values('../.env')
app_token = config.get('APP_TOKEN', None)
headers = {'X-App-Token': app_token}
base = 'https://opendata.mass-cannabis-control.com/resource'

# Get production stats (total employees, total plants, etc.) j3q7-3usu
url = f'{base}/j3q7-3usu.json'
params = {'$limit': 2000, '$order': 'activitysummarydate DESC'}
response = requests.get(url,  headers=headers, params=params)
production = pd.DataFrame(response.json(), dtype=float)
production = reverse_dataframe(production)

# Calculate sales difference.
production['sales'] = production['salestotal'].diff()

# FIX: Fix outlier that appears to have an extra 0.
outlier = production.loc[production.sales >= 10000000]
production.at[outlier.index, 'sales'] = 0

# FIX: Remove negative values.
negatives = production.loc[production.sales < 0]
production.at[negatives.index, 'sales'] = 0

# Aggregate daily production data into monthly and quarterly averages.
production['date'] = pd.to_datetime(production['activitysummarydate'])
production.set_index('date', inplace=True)
monthly_avg_production = production.resample('M').mean()
quarterly_avg_production = production.resample('Q').mean()
monthly_total_production = production.resample('M').sum()
quarterly_total_production = production.resample('Q').sum()

# Get the monthly average price per ounce.
url = f'{base}/rqtv-uenj.json'
params = {'$limit': 10000, '$order': 'date DESC'}
response = requests.get(url,  headers=headers, params=params)
prices = pd.DataFrame(response.json(), dtype=float)
prices = reverse_dataframe(prices)
# prices = end_of_period_timeseries(prices)
# prices.set_index('date')
prices.index = pd.to_datetime(prices.date)
prices = end_of_period_timeseries(prices)

#--------------------------------------------------------------------------
# Get supplemental data from FRED (Federal Reserve Economic Data).
#--------------------------------------------------------------------------

# Initialize Fred client.
config = dotenv_values('../.env')
fred = Fred(api_key=config.get('FRED_API_KEY'))

# Find the observation time start.
observation_start = prices.index.min()

# Get the Federal funds interest rate.
interest_rate = fred.get_series('FEDFUNDS', observation_start=observation_start)
interest_rate = end_of_period_timeseries(interest_rate)

#--------------------------------------------------------------------------
# Estimate a VAR model.
#--------------------------------------------------------------------------

# Calculate inflation.
lag_price = prices.avg_1oz.shift(1)
inflation = (prices.avg_1oz - lag_price) / lag_price
inflation = inflation[1:]

# Restrict the timeframe to match available interest rate and price data.
output = monthly_total_production.loc[
            (monthly_total_production.index >= inflation.index.min()) &
            (monthly_total_production.index <= inflation.index.max())
        ]

# Restrict interest rate to timeframe where inflation is calculated.
interest_rate = interest_rate.loc[interest_rate.index >= inflation.index.min()]

# VAR Vector
variables = [
    output.sales,
    inflation,
    interest_rate,
]
vector = np.column_stack(variables)

# Fit a VAR regression.
model = VAR(vector)
results = model.fit(1)
print(results.summary())

# Fit the best in-sample predicting VAR.
model.select_order(6)
results = model.fit(maxlags=6, ic='bic')
lag_order = results.k_ar
print('Best lag order:', results.k_ar)

# Create a forecast.
horizon = 15
forecast = results.forecast(vector[-lag_order:], horizon)

# Show the data!
results.plot_forecast(horizon)

# Save the data
variables = [
    'total_sales_forecast',
    'inflation_forecast',
    'interest_rate_forecast',
]
forecast_data = pd.DataFrame(forecast, columns=variables)
# forecast_data.index = pd.date_range('2021-04-01', '2022-01-01', freq='m')
forecast_data.to_excel('./data/forecasts.xlsx')