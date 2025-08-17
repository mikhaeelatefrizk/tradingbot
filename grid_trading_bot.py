#!/usr/bin/env python3
"""
Enhanced Binance Grid Trading Bot V6 - High-Density Dynamic Grids
Professional Clean Code Version

MAJOR ENHANCEMENTS:
- 30+ base grid levels (up from 5)
- Dynamic 5-20% range (up from 2%)
- Geometric grid spacing option
- ATR-based volatility analysis
- Partial fill handling
- Market microstructure awareness
- Enhanced performance tracking

Author: Professional Trading Systems
Version: 6.0 Enhanced
License: MIT
"""

import sys
import subprocess
import os
import time
import json
import hmac
import hashlib
import requests
import websocket
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime, timedelta
import traceback
import sqlite3
from collections import deque, defaultdict
import logging
from typing import Dict, List, Optional, Tuple, Any, Union
import signal
from decimal import Decimal, ROUND_DOWN
import queue
import math
import statistics
import numpy as np

# ============================================================================
# DEPENDENCY MANAGEMENT
# ============================================================================

def install_dependencies() -> None:
    """Automatically install required packages with error handling."""
    print("🔧 Checking and installing dependencies...")
    required_packages = ['requests', 'websocket-client', 'numpy']
    
    for package in required_packages:
        try:
            __import__(package.replace('-', '_'))
            print(f"✅ {package} already installed")
        except ImportError:
            print(f"📦 Installing {package}...")
            try:
                subprocess.check_call([sys.executable, "-m", "pip", "install", package])
                print(f"✅ {package} installed successfully")
            except subprocess.CalledProcessError as e:
                print(f"❌ Failed to install {package}: {e}")
                sys.exit(1)

# Install dependencies before proceeding
install_dependencies()

# ============================================================================
# CONFIGURATION CONSTANTS
# ============================================================================

# File paths and logging
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(SCRIPT_DIR, f'grid_bot_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log')

# API Configuration
API_KEY = ""
SECRET_KEY = ""

# Binance Endpoints Configuration
ENDPOINTS = [
    {
        "name": "Binance Testnet",
        "base": "https://testnet.binance.vision",
        "ws": "wss://testnet.binance.vision/ws",
        "stream": "wss://stream.testnet.binance.vision:9443",
        "is_testnet": True
    },
    {
        "name": "Binance Main (Paper Trading)",
        "base": "https://api.binance.com",
        "ws": "wss://stream.binance.com:9443/ws",
        "stream": "wss://stream.binance.com:9443",
        "is_testnet": False
    }
]

# Enhanced Grid Configuration
GRID_CONFIG = {
    'symbols': ['BTCUSDT', 'ETHUSDT', 'BNBUSDT', 'SOLUSDT', 'ADAUSDT'],
    'base_grid_levels': 30,
    'min_grid_levels': 20,
    'max_grid_levels': 50,
    'base_grid_range': 5.0,
    'max_grid_range': 20.0,
    'allocation_per_symbol': 0.15,
    'base_order_size_percent': 0.005,
    'min_order_value': 10.0,
    'update_interval': 30,
    'price_check_interval': 5,
    'base_rebalance_threshold': 0.02,
    'grid_mode': 'geometric',
    'enable_partial_fills': True,
    'check_liquidity': True,
    'state_file': os.path.join(SCRIPT_DIR, 'grid_state.json'),
    'enable_trading': True
}

# API Rate Limits
RATE_LIMITS = {
    'weight_limit': 1200,
    'weight_reset_interval': 60,
    'max_retries': 3,
    'retry_delay': 2
}

# ============================================================================
# LOGGING SETUP
# ============================================================================

def setup_logging() -> logging.Logger:
    """Setup enhanced logging configuration."""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(LOG_FILE, encoding='utf-8'),
            logging.StreamHandler()
        ]
    )
    return logging.getLogger('GridBot')

logger = setup_logging()

# ============================================================================
# GLOBAL STATE MANAGEMENT
# ============================================================================

class GlobalState:
    """Centralized state management for the trading bot."""
    
    def __init__(self):
        self.status = 'disconnected'
        self.endpoint = None
        self.account = {
            'balances': {},
            'total_balance_usdt': 0,
            'maker_commission': 0,
            'taker_commission': 0,
            'can_trade': False,
            'account_type': 'SPOT'
        }
        self.market_prices = {}
        self.market_24hr = {}
        self.activities = deque(maxlen=1000)
        self.open_orders = {}
        self.executed_trades = []
        self.positions = {}
        self.grid_states = {}
        self.grid_orders = {}
        
        self.stats = {
            'total_trades': 0,
            'grid_trades': 0,
            'realized_pnl': 0,
            'unrealized_pnl': 0,
            'total_pnl': 0,
            'fees_paid': 0,
            'win_rate': 0,
            'winning_trades': 0,
            'losing_trades': 0,
            'volume_24h': 0,
            'average_win': 0,
            'average_loss': 0,
            'profit_factor': 0,
            'sharpe_ratio': 0,
            'max_drawdown': 0,
            'total_volume': 0
        }
        
        self.performance = {
            'api_calls': 0,
            'websocket_messages': 0,
            'orders_placed': 0,
            'orders_filled': 0,
            'orders_canceled': 0,
            'errors': 0,
            'start_time': time.time(),
            'uptime': 0
        }
        
        self.selected_symbols = GRID_CONFIG['symbols']
        self.capital_allocation = {
            'USDT': {'free': 0, 'reserved': 0},
            'BTC': {'free': 0, 'reserved': 0},
            'ETH': {'free': 0, 'reserved': 0},
            'BNB': {'free': 0, 'reserved': 0},
            'SOL': {'free': 0, 'reserved': 0},
            'ADA': {'free': 0, 'reserved': 0}
        }
        
        self.grid_metrics = {
            'orders_too_far': 0,
            'insufficient_volatility': 0,
            'grids_adjusted': 0,
            'avg_time_to_fill': 0,
            'partial_fills_handled': 0,
            'liquidity_adjustments': 0,
            'geometric_grids_used': 0,
            'atr_calculations': 0
        }

# Global instances
GLOBAL_STATE = GlobalState()
activity_queue = queue.Queue()

# Exchange info cache
EXCHANGE_INFO = {
    'symbols': {},
    'last_update': 0,
    'server_time': 0,
    'rate_limits': {}
}

# Market analysis cache
MARKET_ANALYSIS = {
    'top_symbols': [],
    'volatility_data': {},
    'correlation_matrix': {},
    'last_update': 0
}

# ============================================================================
# CAPITAL MANAGEMENT
# ============================================================================

class CapitalManager:
    """Thread-safe capital allocation manager to prevent insufficient balance errors."""
    
    def __init__(self):
        self.allocations: Dict[str, Dict[str, float]] = {}
        self.lock = threading.Lock()
        
    def update_balances(self, balances: Dict[str, Dict[str, float]]) -> None:
        """Update available balances from account data."""
        with self.lock:
            for asset, balance in balances.items():
                if asset not in self.allocations:
                    self.allocations[asset] = {'free': 0, 'reserved': 0}
                self.allocations[asset]['free'] = balance.get('free', 0)
    
    def get_available(self, asset: str) -> float:
        """Get available balance for an asset."""
        with self.lock:
            return self.allocations.get(asset, {}).get('free', 0)
    
    def reserve(self, asset: str, amount: float) -> bool:
        """Reserve an amount for an order."""
        with self.lock:
            if asset not in self.allocations:
                return False
            
            available = self.allocations[asset]['free']
            if available >= amount:
                self.allocations[asset]['free'] -= amount
                self.allocations[asset]['reserved'] += amount
                return True
            return False
    
    def release(self, asset: str, amount: float) -> None:
        """Release a reserved amount."""
        with self.lock:
            if asset in self.allocations:
                self.allocations[asset]['reserved'] = max(0, 
                    self.allocations[asset]['reserved'] - amount)
                self.allocations[asset]['free'] += amount
    
    def get_allocation_info(self) -> Dict[str, Dict[str, float]]:
        """Get current allocation information."""
        with self.lock:
            return dict(self.allocations)

capital_manager = CapitalManager()

# ============================================================================
# BINANCE API WRAPPER
# ============================================================================

class BinanceAPI:
    """Enhanced Binance API wrapper with comprehensive error handling."""
    
    def __init__(self, api_key: str, secret_key: str):
        self.api_key = api_key
        self.secret_key = secret_key
        self.session = requests.Session()
        self.session.headers.update({'X-MBX-APIKEY': api_key})
        self.endpoint: Optional[Dict] = None
        self.weight_used = 0
        self.weight_limit = RATE_LIMITS['weight_limit']
        self.last_weight_reset = time.time()
        
    def set_endpoint(self, endpoint: Dict) -> bool:
        """Test and set endpoint with comprehensive validation."""
        try:
            response = self.session.get(f"{endpoint['base']}/api/v3/ping", timeout=5)
            if response.status_code != 200:
                return False
                
            self.endpoint = endpoint
            logger.info(f"Connected to {endpoint['name']}")
            
            # Get server time for synchronization
            server_time = self._request('GET', '/api/v3/time', signed=False)
            if server_time:
                EXCHANGE_INFO['server_time'] = server_time['serverTime']
                local_time = int(time.time() * 1000)
                time_diff = abs(server_time['serverTime'] - local_time)
                if time_diff > 1000:
                    logger.warning(f"Time sync issue: {time_diff}ms difference")
            
            self._update_exchange_info()
            self._validate_account()
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to connect to {endpoint['name']}: {e}")
            return False
    
    def _validate_account(self) -> None:
        """Validate account information and trading permissions."""
        account = self.get_account()
        if account:
            GLOBAL_STATE.account['can_trade'] = account.get('canTrade', False)
            GLOBAL_STATE.account['account_type'] = account.get('accountType', 'SPOT')
            GLOBAL_STATE.account['maker_commission'] = float(account.get('makerCommission', 10)) / 10000
            GLOBAL_STATE.account['taker_commission'] = float(account.get('takerCommission', 10)) / 10000
            
            logger.info(f"Account validated - Type: {GLOBAL_STATE.account['account_type']}, "
                       f"Can trade: {GLOBAL_STATE.account['can_trade']}")
    
    def _update_exchange_info(self) -> None:
        """Update comprehensive exchange information."""
        try:
            response = self._request('GET', '/api/v3/exchangeInfo', signed=False)
            if not response:
                return
                
            # Store rate limits
            for limit in response.get('rateLimits', []):
                EXCHANGE_INFO['rate_limits'][limit['rateLimitType']] = {
                    'limit': limit['limit'],
                    'interval': limit['interval'],
                    'intervalNum': limit['intervalNum']
                }
            
            # Process trading pairs
            usdt_pairs = []
            for symbol_info in response.get('symbols', []):
                if (symbol_info['symbol'] in GRID_CONFIG['symbols'] or
                    (symbol_info['quoteAsset'] == 'USDT' and 
                     symbol_info['status'] == 'TRADING' and
                     symbol_info['isSpotTradingAllowed'])):
                    
                    symbol_data = {
                        'symbol': symbol_info['symbol'],
                        'baseAsset': symbol_info['baseAsset'],
                        'quoteAsset': symbol_info['quoteAsset'],
                        'status': symbol_info['status'],
                        'filters': {f['filterType']: f for f in symbol_info['filters']}
                    }
                    
                    EXCHANGE_INFO['symbols'][symbol_info['symbol']] = symbol_data
                    usdt_pairs.append(symbol_info['symbol'])
            
            EXCHANGE_INFO['last_update'] = time.time()
            logger.info(f"Exchange info updated: {len(usdt_pairs)} USDT pairs available")
            
        except Exception as e:
            logger.error(f"Failed to update exchange info: {e}")
    
    def _check_weight_limit(self, weight: int = 1) -> None:
        """Check and manage API weight limits."""
        current_time = time.time()
        
        if current_time - self.last_weight_reset > RATE_LIMITS['weight_reset_interval']:
            self.weight_used = 0
            self.last_weight_reset = current_time
        
        if self.weight_used + weight > self.weight_limit * 0.8:
            wait_time = RATE_LIMITS['weight_reset_interval'] - (current_time - self.last_weight_reset)
            if wait_time > 0:
                logger.warning(f"Approaching rate limit, waiting {wait_time:.1f}s")
                time.sleep(wait_time)
                self.weight_used = 0
                self.last_weight_reset = time.time()
        
        self.weight_used += weight
    
    def _sign_request(self, params: Dict) -> Dict:
        """Sign request with proper timestamp validation."""
        params = params.copy()
        
        if EXCHANGE_INFO.get('server_time'):
            time_passed = (time.time() * 1000) - EXCHANGE_INFO['server_time']
            params['timestamp'] = int(EXCHANGE_INFO['server_time'] + time_passed)
        else:
            params['timestamp'] = int(time.time() * 1000)
            
        params['recvWindow'] = 5000
        
        query_string = '&'.join([f"{k}={v}" for k, v in params.items()])
        signature = hmac.new(
            self.secret_key.encode('utf-8'),
            query_string.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        
        params['signature'] = signature
        return params
    
    def _request(self, method: str, path: str, signed: bool = True, 
                weight: int = 1, **kwargs) -> Optional[Dict]:
        """Enhanced request method with comprehensive error handling."""
        if not self.endpoint:
            logger.error("No endpoint configured")
            return None
        
        self._check_weight_limit(weight)
        url = f"{self.endpoint['base']}{path}"
        
        for attempt in range(RATE_LIMITS['max_retries']):
            try:
                if signed and 'params' in kwargs:
                    kwargs['params'] = self._sign_request(kwargs['params'])
                
                response = self.session.request(method, url, timeout=10, **kwargs)
                
                if 'X-MBX-USED-WEIGHT' in response.headers:
                    self.weight_used = int(response.headers['X-MBX-USED-WEIGHT'])
                
                GLOBAL_STATE.performance['api_calls'] += 1
                
                if response.status_code == 200:
                    return response.json()
                elif response.status_code == 429:
                    retry_after = int(response.headers.get('Retry-After', 60))
                    logger.warning(f"Rate limit hit, waiting {retry_after}s")
                    time.sleep(retry_after)
                elif response.status_code == 418:
                    logger.error("IP has been banned")
                    GLOBAL_STATE.status = 'banned'
                    return None
                else:
                    error_msg = response.text
                    logger.error(f"API error {response.status_code}: {error_msg}")
                    self._handle_api_error(response)
                    
            except requests.exceptions.Timeout:
                logger.error(f"Request timeout (attempt {attempt + 1}/{RATE_LIMITS['max_retries']})")
            except Exception as e:
                logger.error(f"Request failed (attempt {attempt + 1}/{RATE_LIMITS['max_retries']}): {e}")
                
            if attempt < RATE_LIMITS['max_retries'] - 1:
                time.sleep(RATE_LIMITS['retry_delay'] ** attempt)
        
        GLOBAL_STATE.performance['errors'] += 1
        return None
    
    def _handle_api_error(self, response: requests.Response) -> None:
        """Handle specific API errors."""
        try:
            error_data = response.json()
            error_code = error_data.get('code')
            
            if error_code == -1021:
                logger.warning("Timestamp sync issue, updating server time...")
                self._update_server_time()
            elif error_code == -2010:
                logger.warning("Insufficient balance detected")
        except:
            pass
    
    def _update_server_time(self) -> None:
        """Update server time for better synchronization."""
        server_time = self._request('GET', '/api/v3/time', signed=False, weight=1)
        if server_time:
            EXCHANGE_INFO['server_time'] = server_time['serverTime']
    
    # API Methods
    def get_account(self) -> Optional[Dict]:
        """Get account information."""
        return self._request('GET', '/api/v3/account', params={}, weight=10)
    
    def get_all_tickers(self) -> Optional[List[Dict]]:
        """Get all ticker prices."""
        return self._request('GET', '/api/v3/ticker/price', signed=False, weight=2)
    
    def get_ticker_24hr(self, symbol: str = None) -> Optional[Union[Dict, List[Dict]]]:
        """Get 24hr ticker statistics."""
        params = {'symbol': symbol} if symbol else {}
        weight = 1 if symbol else 40
        return self._request('GET', '/api/v3/ticker/24hr', signed=False, 
                           params=params, weight=weight)
    
    def get_order_book(self, symbol: str, limit: int = 20) -> Optional[Dict]:
        """Get order book depth."""
        weight = 1 if limit <= 100 else 5 if limit <= 500 else 10
        return self._request('GET', '/api/v3/depth', signed=False,
                           params={'symbol': symbol, 'limit': limit}, weight=weight)
    
    def get_klines(self, symbol: str, interval: str = '1m', 
                  limit: int = 100) -> Optional[List]:
        """Get kline/candlestick data."""
        return self._request('GET', '/api/v3/klines', signed=False,
                           params={'symbol': symbol, 'interval': interval, 'limit': limit}, 
                           weight=1)
    
    def get_my_trades(self, symbol: str, limit: int = 500, 
                     fromId: int = None) -> Optional[List[Dict]]:
        """Get executed trades with pagination."""
        params = {'symbol': symbol, 'limit': limit}
        if fromId:
            params['fromId'] = fromId
        return self._request('GET', '/api/v3/myTrades', params=params, weight=10)
    
    def place_order(self, **params) -> Optional[Dict]:
        """Place an order with comprehensive validation."""
        symbol = params.get('symbol')
        if not symbol or symbol not in GRID_CONFIG['symbols']:
            logger.error(f"Invalid symbol: {symbol}")
            return None
        
        if not self._validate_order(params):
            return None
        
        order = self._request('POST', '/api/v3/order', params=params, weight=1)
        
        if order:
            GLOBAL_STATE.performance['orders_placed'] += 1
            logger.info(f"✅ Order placed: {params['side']} {params['quantity']} "
                       f"{symbol} @ {params.get('price', 'MARKET')}")
            
            self._add_order_activity(order, params)
        
        return order
    
    def _validate_order(self, params: Dict) -> bool:
        """Comprehensive order validation against exchange rules."""
        symbol = params.get('symbol')
        if symbol not in EXCHANGE_INFO['symbols']:
            logger.error(f"No exchange info for {symbol}")
            return False
        
        symbol_info = EXCHANGE_INFO['symbols'][symbol]
        filters = symbol_info['filters']
        
        # Validate price (for LIMIT orders)
        if params.get('type') == 'LIMIT' and 'price' in params:
            if not self._validate_price(params, filters):
                return False
        
        # Validate quantity
        if not self._validate_quantity(params, filters):
            return False
        
        # Validate notional
        if not self._validate_notional(params, filters):
            return False
        
        return True
    
    def _validate_price(self, params: Dict, filters: Dict) -> bool:
        """Validate price against PRICE_FILTER."""
        if 'PRICE_FILTER' not in filters:
            return True
            
        price_filter = filters['PRICE_FILTER']
        price = Decimal(str(params.get('price', 0)))
        min_price = Decimal(price_filter['minPrice'])
        max_price = Decimal(price_filter['maxPrice'])
        tick_size = Decimal(price_filter['tickSize'])
        
        if price < min_price or price > max_price:
            logger.error(f"Price {price} outside valid range [{min_price}, {max_price}]")
            return False
        
        # Round to tick size
        if tick_size > 0:
            precision = int(round(-math.log10(float(tick_size))))
            params['price'] = str(round(float(price), precision))
        
        return True
    
    def _validate_quantity(self, params: Dict, filters: Dict) -> bool:
        """Validate quantity against LOT_SIZE filter."""
        if 'LOT_SIZE' not in filters:
            return True
            
        lot_filter = filters['LOT_SIZE']
        quantity = Decimal(str(params.get('quantity', 0)))
        min_qty = Decimal(lot_filter['minQty'])
        max_qty = Decimal(lot_filter['maxQty'])
        step_size = Decimal(lot_filter['stepSize'])
        
        if quantity < min_qty or quantity > max_qty:
            logger.error(f"Quantity {quantity} outside valid range [{min_qty}, {max_qty}]")
            return False
        
        # Round to step size
        if step_size > 0:
            precision = int(round(-math.log10(float(step_size))))
            params['quantity'] = str(round(float(quantity), precision))
        
        return True
    
    def _validate_notional(self, params: Dict, filters: Dict) -> bool:
        """Validate notional value against MIN_NOTIONAL filter."""
        if 'MIN_NOTIONAL' not in filters:
            return True
            
        min_notional = Decimal(filters['MIN_NOTIONAL']['minNotional'])
        
        if params.get('type') == 'LIMIT':
            notional = Decimal(str(params.get('price', 0))) * Decimal(str(params.get('quantity', 0)))
        else:
            current_price = GLOBAL_STATE.market_prices.get(params.get('symbol'), 0)
            notional = Decimal(str(current_price)) * Decimal(str(params.get('quantity', 0)))
        
        if notional < min_notional:
            logger.error(f"Order value ${notional} below minimum ${min_notional}")
            return False
        
        return True
    
    def _add_order_activity(self, order: Dict, params: Dict) -> None:
        """Add order to activity queue."""
        activity_queue.put({
            'type': 'order_placed',
            'symbol': params['symbol'],
            'side': params['side'],
            'price': float(params.get('price', 0)),
            'quantity': float(params['quantity']),
            'order_id': order['orderId'],
            'status': order['status'],
            'time': order['transactTime']
        })
    
    def cancel_order(self, symbol: str, order_id: int) -> Optional[Dict]:
        """Cancel an order."""
        if symbol not in GRID_CONFIG['symbols']:
            return None
            
        result = self._request('DELETE', '/api/v3/order', 
                             params={'symbol': symbol, 'orderId': order_id}, weight=1)
        if result:
            GLOBAL_STATE.performance['orders_canceled'] += 1
        return result
    
    def get_open_orders(self, symbol: Optional[str] = None) -> Optional[List[Dict]]:
        """Get open orders."""
        if symbol and symbol not in GRID_CONFIG['symbols']:
            return []
        params = {'symbol': symbol} if symbol else {}
        weight = 3 if symbol else 40
        return self._request('GET', '/api/v3/openOrders', params=params, weight=weight)
    
    def get_listen_key(self) -> Optional[str]:
        """Get listen key for user data stream."""
        result = self._request('POST', '/api/v3/userDataStream', signed=False, weight=1)
        return result.get('listenKey') if result else None
    
    def keepalive_listen_key(self, listen_key: str) -> bool:
        """Keep listen key alive."""
        result = self._request('PUT', f'/api/v3/userDataStream?listenKey={listen_key}', 
                             signed=False, weight=1)
        return result is not None

# ============================================================================
# MARKET ANALYZER
# ============================================================================

class MarketAnalyzer:
    """Enhanced market analyzer with ATR and advanced volatility calculations."""
    
    def __init__(self, api: BinanceAPI):
        self.api = api
        self.analysis_cache: Dict = {}
        self.last_analysis = 0
        
    def analyze_market(self) -> List[str]:
        """Analyze market and select optimal trading pairs."""
        logger.info("🔍 Analyzing market conditions...")
        
        all_tickers = self.api.get_ticker_24hr()
        if not all_tickers:
            logger.error("Failed to get market data")
            return []
        
        candidates = self._filter_candidates(all_tickers)
        selected = self._score_and_select(candidates)
        
        # Update analysis cache
        MARKET_ANALYSIS['top_symbols'] = selected
        MARKET_ANALYSIS['last_update'] = time.time()
        
        selected_symbols = [s['symbol'] for s in selected]
        logger.info(f"✅ Selected {len(selected_symbols)} symbols: {', '.join(selected_symbols)}")
        
        return selected_symbols
    
    def _filter_candidates(self, tickers: List[Dict]) -> List[Dict]:
        """Filter and prepare candidate symbols."""
        candidates = []
        
        for ticker in tickers:
            symbol = ticker['symbol']
            if (symbol.endswith('USDT') and 
                symbol in EXCHANGE_INFO['symbols'] and
                float(ticker['quoteVolume']) > 1000000):
                
                candidates.append({
                    'symbol': symbol,
                    'volume': float(ticker['quoteVolume']),
                    'price_change_percent': float(ticker['priceChangePercent']),
                    'high_low_ratio': float(ticker['highPrice']) / float(ticker['lowPrice']) 
                                    if float(ticker['lowPrice']) > 0 else 1,
                    'count': int(ticker['count']),
                    'weighted_avg_price': float(ticker['weightedAvgPrice'])
                })
        
        return candidates
    
    def _score_and_select(self, candidates: List[Dict]) -> List[Dict]:
        """Score candidates and select the best ones."""
        for candidate in candidates:
            volatility = abs(candidate['price_change_percent']) * (candidate['high_low_ratio'] - 1)
            liquidity_score = math.log10(candidate['volume']) * math.log10(candidate['count'] + 1)
            candidate['score'] = volatility * liquidity_score
        
        candidates.sort(key=lambda x: x['score'], reverse=True)
        
        selected = []
        for candidate in candidates[:10]:
            if self._validate_spread(candidate['symbol']):
                selected.append(candidate)
                if len(selected) >= 5:
                    break
        
        return selected
    
    def _validate_spread(self, symbol: str) -> bool:
        """Validate spread for a symbol."""
        order_book = self.api.get_order_book(symbol, limit=5)
        if not order_book or not order_book.get('bids') or not order_book.get('asks'):
            return False
        
        best_bid = float(order_book['bids'][0][0])
        best_ask = float(order_book['asks'][0][0])
        
        if best_bid > 0 and best_ask > 0:
            spread_percent = ((best_ask - best_bid) / best_bid) * 100
            return spread_percent < 0.5
        
        return False
    
    def calculate_atr(self, klines: List, period: int = 14) -> float:
        """Calculate Average True Range for volatility measurement."""
        if len(klines) < period + 1:
            return 0
        
        GLOBAL_STATE.grid_metrics['atr_calculations'] += 1
        
        true_ranges = []
        for i in range(1, len(klines)):
            current = klines[i]
            previous = klines[i-1]
            
            high = float(current[2])
            low = float(current[3])
            prev_close = float(previous[4])
            
            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
            true_ranges.append(tr)
        
        if len(true_ranges) >= period:
            return sum(true_ranges[-period:]) / period
        return sum(true_ranges) / len(true_ranges) if true_ranges else 0
    
    def calculate_dynamic_grid_params(self, symbol: str) -> Dict:
        """Calculate optimal grid parameters with ATR and microstructure analysis."""
        klines_1h = self.api.get_klines(symbol, interval='1h', limit=24)
        klines_15m = self.api.get_klines(symbol, interval='15m', limit=96)
        klines_1m = self.api.get_klines(symbol, interval='1m', limit=20)
        
        if not all([klines_1h, klines_15m, klines_1m]):
            return self._get_default_params()
        
        current_price = float(klines_1h[-1][4])
        
        # Calculate volatility metrics
        atr_1h = self.calculate_atr(klines_1h)
        atr_15m = self.calculate_atr(klines_15m)
        
        prices_15m = [float(k[4]) for k in klines_15m]
        returns_15m = [(prices_15m[i] - prices_15m[i-1]) / prices_15m[i-1] 
                      for i in range(1, len(prices_15m))]
        
        std_dev = np.std(returns_15m) if returns_15m else 0.01
        atr_pct = atr_1h / current_price if current_price > 0 else 0.01
        
        # Dynamic parameter calculation
        params = self._calculate_grid_parameters(atr_pct, std_dev)
        
        # Liquidity adjustment
        if GRID_CONFIG['check_liquidity']:
            liquidity_score = self._calculate_liquidity_score(symbol, current_price)
            params = self._adjust_for_liquidity(params, liquidity_score)
        
        return params
    
    def _calculate_grid_parameters(self, atr_pct: float, std_dev: float) -> Dict:
        """Calculate grid parameters based on volatility metrics."""
        base_levels = GRID_CONFIG['base_grid_levels']
        min_levels = GRID_CONFIG['min_grid_levels']
        max_levels = GRID_CONFIG['max_grid_levels']
        base_range = GRID_CONFIG['base_grid_range']
        max_range = GRID_CONFIG['max_grid_range']
        
        if atr_pct > 0.03 or std_dev > 0.02:  # High volatility
            grid_levels = max(min_levels, base_levels - 10)
            grid_range = min(max_range, max(atr_pct * 300, base_range * 1.5))
            rebalance_threshold = 0.04
            order_size_multiplier = 0.8
        elif atr_pct < 0.01 and std_dev < 0.005:  # Low volatility
            grid_levels = min(max_levels, base_levels + 20)
            grid_range = max(base_range, atr_pct * 500)
            rebalance_threshold = 0.015
            order_size_multiplier = 1.2
        else:  # Normal volatility
            grid_levels = base_levels
            grid_range = max(base_range, atr_pct * 400)
            rebalance_threshold = GRID_CONFIG['base_rebalance_threshold']
            order_size_multiplier = 1.0
        
        grid_range = min(grid_range, max_range)
        order_size = (GRID_CONFIG['allocation_per_symbol'] / grid_levels / 2) * order_size_multiplier
        order_size = max(order_size, GRID_CONFIG['base_order_size_percent'])
        
        return {
            'grid_levels': int(grid_levels),
            'grid_range_percent': grid_range,
            'order_size_percent': order_size,
            'rebalance_threshold': rebalance_threshold,
            'volatility': std_dev,
            'atr': atr_pct * 100,  # Convert to percentage
            'atr_pct': atr_pct,
            'liquidity_score': 1.0,
            'min_order_value': GRID_CONFIG['min_order_value'],
            'grid_mode': GRID_CONFIG['grid_mode']
        }
    
    def _calculate_liquidity_score(self, symbol: str, current_price: float) -> float:
        """Calculate liquidity score based on order book depth."""
        order_book = self.api.get_order_book(symbol, limit=50)
        if not order_book:
            return 0.5
        
        try:
            bids = order_book.get('bids', [])
            asks = order_book.get('asks', [])
            
            if not bids or not asks:
                return 0.5
            
            price_range = current_price * 0.01
            
            bid_depth = sum(float(bid[1]) * float(bid[0]) for bid in bids 
                           if float(bid[0]) >= current_price - price_range)
            ask_depth = sum(float(ask[1]) * float(ask[0]) for ask in asks 
                           if float(ask[0]) <= current_price + price_range)
            
            total_depth = bid_depth + ask_depth
            balance = min(bid_depth, ask_depth) / max(bid_depth, ask_depth) \
                     if max(bid_depth, ask_depth) > 0 else 0
            
            depth_score = min(1.0, total_depth / 100000)
            return (depth_score + balance) / 2
            
        except Exception as e:
            logger.error(f"Error calculating liquidity score: {e}")
            return 0.5
    
    def _adjust_for_liquidity(self, params: Dict, liquidity_score: float) -> Dict:
        """Adjust parameters based on liquidity score."""
        if liquidity_score < 0.5:
            params['grid_levels'] = max(GRID_CONFIG['min_grid_levels'], 
                                      int(params['grid_levels'] * 0.7))
            params['grid_range_percent'] *= 1.3
            GLOBAL_STATE.grid_metrics['liquidity_adjustments'] += 1
        
        params['liquidity_score'] = liquidity_score
        return params
    
    def _get_default_params(self) -> Dict:
        """Get default parameters if analysis fails."""
        return {
            'grid_levels': GRID_CONFIG['base_grid_levels'],
            'grid_range_percent': GRID_CONFIG['base_grid_range'],
            'order_size_percent': GRID_CONFIG['base_order_size_percent'],
            'rebalance_threshold': GRID_CONFIG['base_rebalance_threshold'],
            'volatility': 0.01,
            'atr': 1.0,
            'atr_pct': 0.01,
            'liquidity_score': 1.0,
            'min_order_value': GRID_CONFIG['min_order_value'],
            'grid_mode': GRID_CONFIG['grid_mode']
        }

# ============================================================================
# TRADING ENGINE
# ============================================================================

class TradingEngine:
    """Enhanced trading engine with accurate P&L tracking."""
    
    def __init__(self, api: BinanceAPI):
        self.api = api
        self.trades_lock = threading.Lock()
        self.trades_by_symbol = defaultdict(list)
        self.closed_positions = []
        
    def update_market_prices(self) -> None:
        """Update all market prices from API."""
        tickers = self.api.get_all_tickers()
        if tickers:
            for ticker in tickers:
                GLOBAL_STATE.market_prices[ticker['symbol']] = float(ticker['price'])
            logger.info(f"Updated {len(GLOBAL_STATE.market_prices)} market prices")
    
    def update_24hr_stats(self) -> None:
        """Update 24hr statistics for selected symbols."""
        for symbol in GRID_CONFIG['symbols']:
            ticker = self.api.get_ticker_24hr(symbol)
            if ticker:
                GLOBAL_STATE.market_24hr[symbol] = {
                    'priceChange': float(ticker['priceChange']),
                    'priceChangePercent': float(ticker['priceChangePercent']),
                    'weightedAvgPrice': float(ticker['weightedAvgPrice']),
                    'highPrice': float(ticker['highPrice']),
                    'lowPrice': float(ticker['lowPrice']),
                    'volume': float(ticker['volume']),
                    'quoteVolume': float(ticker['quoteVolume']),
                    'count': int(ticker['count'])
                }
    
    def update_account_balances(self) -> None:
        """Update account balances with real API data."""
        account = self.api.get_account()
        if not account:
            return
        
        self._update_account_info(account)
        balances = self._process_balances(account.get('balances', []))
        
        GLOBAL_STATE.account['balances'] = balances
        capital_manager.update_balances(balances)
        
        total_usdt = self._calculate_total_balance(balances)
        GLOBAL_STATE.account['total_balance_usdt'] = total_usdt
        GLOBAL_STATE.capital_allocation = capital_manager.get_allocation_info()
        
        logger.info(f"Total account balance: ${total_usdt:.2f} USDT")
    
    def _update_account_info(self, account: Dict) -> None:
        """Update account information."""
        GLOBAL_STATE.account['can_trade'] = account.get('canTrade', False)
        GLOBAL_STATE.account['maker_commission'] = float(account.get('makerCommission', 10)) / 10000
        GLOBAL_STATE.account['taker_commission'] = float(account.get('takerCommission', 10)) / 10000
    
    def _process_balances(self, raw_balances: List[Dict]) -> Dict:
        """Process raw balance data."""
        balances = {}
        for balance in raw_balances:
            asset = balance['asset']
            free = float(balance['free'])
            locked = float(balance['locked'])
            
            if free > 0 or locked > 0:
                balances[asset] = {
                    'free': free,
                    'locked': locked,
                    'total': free + locked
                }
        return balances
    
    def _calculate_total_balance(self, balances: Dict) -> float:
        """Calculate total balance in USDT."""
        total_usdt = balances.get('USDT', {}).get('total', 0)
        
        for asset, balance in balances.items():
            if asset != 'USDT' and balance['total'] > 0:
                symbol = f"{asset}USDT"
                if symbol in GLOBAL_STATE.market_prices:
                    value_usdt = balance['total'] * GLOBAL_STATE.market_prices[symbol]
                    total_usdt += value_usdt
        
        return total_usdt
    
    def sync_trades_history(self) -> None:
        """Sync all trades from exchange with pagination."""
        all_trades = []
        
        with self.trades_lock:
            self.trades_by_symbol.clear()
            
            for symbol in GRID_CONFIG['symbols']:
                symbol_trades = self._get_all_trades_for_symbol(symbol)
                self.trades_by_symbol[symbol] = symbol_trades
                all_trades.extend(symbol_trades)
        
        all_trades.sort(key=lambda x: x['time'])
        
        with self.trades_lock:
            GLOBAL_STATE.executed_trades = all_trades
            
        self.calculate_positions_and_pnl()
        logger.info(f"Synced {len(all_trades)} trades from exchange")
    
    def _get_all_trades_for_symbol(self, symbol: str) -> List[Dict]:
        """Get all trades for a specific symbol with pagination."""
        symbol_trades = []
        from_id = None
        
        while True:
            trades = self.api.get_my_trades(symbol, limit=500, fromId=from_id)
            if not trades:
                break
                
            symbol_trades.extend(trades)
            
            if len(trades) < 500:
                break
                
            from_id = trades[-1]['id'] + 1
        
        return symbol_trades
    
    def calculate_positions_and_pnl(self) -> None:
        """Calculate positions and P&L from executed trades using FIFO method."""
        positions = {}
        self.closed_positions = []
        
        total_realized_pnl = 0
        total_fees_paid = 0
        total_volume = 0
        
        with self.trades_lock:
            for symbol, trades in self.trades_by_symbol.items():
                if not trades:
                    continue
                    
                position, symbol_pnl, symbol_fees, symbol_volume = \
                    self._calculate_symbol_position(symbol, trades)
                
                total_realized_pnl += symbol_pnl
                total_fees_paid += symbol_fees
                total_volume += symbol_volume
                
                if position['quantity'] > 0 or position['realized_pnl'] != 0:
                    positions[symbol] = position
        
        total_unrealized_pnl = self._calculate_unrealized_pnl(positions)
        self._update_trading_stats(total_realized_pnl, total_unrealized_pnl, 
                                 total_fees_paid, total_volume)
        
        GLOBAL_STATE.positions = positions
    
    def _calculate_symbol_position(self, symbol: str, trades: List[Dict]) -> Tuple:
        """Calculate position for a specific symbol using FIFO."""
        position = {
            'symbol': symbol,
            'quantity': 0,
            'total_cost': 0,
            'realized_pnl': 0,
            'trades': []
        }
        
        buy_queue = deque()
        symbol_pnl = 0
        symbol_fees = 0
        symbol_volume = 0
        
        for trade in sorted(trades, key=lambda x: x['time']):
            trade_pnl, trade_fees = self._process_trade(trade, position, buy_queue)
            symbol_pnl += trade_pnl
            symbol_fees += trade_fees
            symbol_volume += float(trade['quoteQty'])
            
            position['trades'].append(trade)
        
        position['realized_pnl'] = symbol_pnl
        return position, symbol_pnl, symbol_fees, symbol_volume
    
    def _process_trade(self, trade: Dict, position: Dict, buy_queue: deque) -> Tuple[float, float]:
        """Process individual trade and update position."""
        qty = float(trade['qty'])
        price = float(trade['price'])
        commission = float(trade['commission'])
        commission_asset = trade['commissionAsset']
        is_buyer = trade['isBuyer']
        
        commission_usdt = self._convert_commission_to_usdt(commission, commission_asset, price, trade['symbol'])
        
        if is_buyer:
            buy_queue.append({
                'qty': qty,
                'price': price,
                'time': trade['time'],
                'commission': commission_usdt
            })
            position['quantity'] += qty
            position['total_cost'] += qty * price
            return 0, commission_usdt
        else:
            trade_pnl = self._calculate_sell_pnl(qty, price, buy_queue) - commission_usdt
            position['quantity'] -= qty
            position['total_cost'] = max(0, position['total_cost'] - qty * price)
            
            self.closed_positions.append({
                'symbol': trade['symbol'],
                'pnl': trade_pnl,
                'time': trade['time']
            })
            
            return trade_pnl, commission_usdt
    
    def _convert_commission_to_usdt(self, commission: float, asset: str, 
                                   price: float, symbol: str) -> float:
        """Convert commission to USDT value."""
        if asset == 'USDT':
            return commission
        elif asset == EXCHANGE_INFO['symbols'].get(symbol, {}).get('baseAsset'):
            return commission * price
        else:
            comm_symbol = f"{asset}USDT"
            if comm_symbol in GLOBAL_STATE.market_prices:
                return commission * GLOBAL_STATE.market_prices[comm_symbol]
        return 0
    
    def _calculate_sell_pnl(self, sell_qty: float, sell_price: float, 
                           buy_queue: deque) -> float:
        """Calculate P&L for sell trade using FIFO."""
        remaining_qty = sell_qty
        trade_pnl = 0
        
        while remaining_qty > 0 and buy_queue:
            buy_trade = buy_queue[0]
            
            if buy_trade['qty'] <= remaining_qty:
                trade_qty = buy_trade['qty']
                pnl = (sell_price - buy_trade['price']) * trade_qty
                trade_pnl += pnl
                remaining_qty -= trade_qty
                buy_queue.popleft()
            else:
                pnl = (sell_price - buy_trade['price']) * remaining_qty
                trade_pnl += pnl
                buy_trade['qty'] -= remaining_qty
                remaining_qty = 0
        
        return trade_pnl
    
    def _calculate_unrealized_pnl(self, positions: Dict) -> float:
        """Calculate unrealized P&L for open positions."""
        total_unrealized = 0
        
        for symbol, pos in positions.items():
            if pos['quantity'] > 0 and symbol in GLOBAL_STATE.market_prices:
                current_price = GLOBAL_STATE.market_prices[symbol]
                avg_cost = pos['total_cost'] / pos['quantity'] if pos['quantity'] > 0 else 0
                unrealized = (current_price - avg_cost) * pos['quantity']
                
                pos['unrealized_pnl'] = unrealized
                pos['avg_price'] = avg_cost
                pos['current_price'] = current_price
                pos['value'] = current_price * pos['quantity']
                total_unrealized += unrealized
            else:
                pos['unrealized_pnl'] = 0
                pos['avg_price'] = 0
                pos['current_price'] = GLOBAL_STATE.market_prices.get(symbol, 0)
                pos['value'] = 0
        
        return total_unrealized
    
    def _update_trading_stats(self, realized_pnl: float, unrealized_pnl: float,
                             fees_paid: float, volume: float) -> None:
        """Update trading statistics."""
        winning_trades = len([p for p in self.closed_positions if p['pnl'] > 0])
        losing_trades = len([p for p in self.closed_positions if p['pnl'] < 0])
        total_trades = winning_trades + losing_trades
        
        avg_win = np.mean([p['pnl'] for p in self.closed_positions if p['pnl'] > 0]) \
                 if winning_trades > 0 else 0
        avg_loss = abs(np.mean([p['pnl'] for p in self.closed_positions if p['pnl'] < 0])) \
                  if losing_trades > 0 else 0
        
        profit_factor = (avg_win * winning_trades) / (avg_loss * losing_trades) \
                       if losing_trades > 0 and avg_loss > 0 else 0
        
        sharpe_ratio = 0
        if len(self.closed_positions) > 1:
            returns = [p['pnl'] for p in self.closed_positions]
            if np.std(returns) > 0:
                sharpe_ratio = np.mean(returns) / np.std(returns) * np.sqrt(252)
        
        GLOBAL_STATE.stats.update({
            'total_trades': len(GLOBAL_STATE.executed_trades),
            'grid_trades': total_trades,
            'realized_pnl': realized_pnl,
            'unrealized_pnl': unrealized_pnl,
            'total_pnl': realized_pnl + unrealized_pnl,
            'fees_paid': fees_paid,
            'winning_trades': winning_trades,
            'losing_trades': losing_trades,
            'win_rate': (winning_trades / total_trades * 100) if total_trades > 0 else 0,
            'average_win': avg_win,
            'average_loss': avg_loss,
            'profit_factor': profit_factor,
            'sharpe_ratio': sharpe_ratio,
            'total_volume': volume
        })
        
        logger.info(f"📊 P&L Update - Realized: ${realized_pnl:.2f}, "
                   f"Unrealized: ${unrealized_pnl:.2f}, "
                   f"Win Rate: {GLOBAL_STATE.stats['win_rate']:.1f}%")

# ============================================================================
# ENHANCED GRID MANAGER
# ============================================================================

class EnhancedGridManager:
    """Enhanced grid manager with high-density grids and geometric spacing."""
    
    def __init__(self, symbol: str, api: BinanceAPI, trading_engine: TradingEngine, params: Dict):
        self.symbol = symbol
        self.api = api
        self.trading_engine = trading_engine
        self.params = params
        self.grid_orders = {'buy': [], 'sell': []}
        self.last_update = 0
        self.grid_center = 0
        self.price_history = deque(maxlen=50)
        self.active = False
        self.filled_orders = set()
        self.order_map = {}
        self.partial_fills = {}
        
    def update(self) -> None:
        """Update grid based on market conditions."""
        if self.symbol not in GLOBAL_STATE.market_prices:
            return
        
        current_price = GLOBAL_STATE.market_prices[self.symbol]
        self.price_history.append((current_price, time.time()))
        
        self._update_volatility()
        
        if not self.active or time.time() - self.last_update > 300:
            self._setup_enhanced_grid(current_price)
        
        self._check_filled_orders()
        
        if GRID_CONFIG['enable_partial_fills']:
            self._handle_partial_fills()
    
    def check_price_movement(self) -> None:
        """Check if price movement requires grid adjustment."""
        if not self.active or self.grid_center == 0:
            return
        
        current_price = GLOBAL_STATE.market_prices.get(self.symbol, 0)
        if current_price == 0:
            return
        
        price_drift = abs(current_price - self.grid_center) / self.grid_center
        rebalance_threshold = self.params.get('rebalance_threshold', 
                                            GRID_CONFIG['base_rebalance_threshold'])
        
        if price_drift > rebalance_threshold:
            logger.info(f"Price drift {price_drift:.2%} detected for {self.symbol}, "
                       f"adjusting grid (threshold: {rebalance_threshold:.2%})")
            GLOBAL_STATE.grid_metrics['grids_adjusted'] += 1
            self._setup_enhanced_grid(current_price)
    
    def _update_volatility(self) -> None:
        """Update volatility from real price data."""
        if len(self.price_history) < 10:
            return
        
        prices = [p[0] for p in self.price_history]
        returns = [(prices[i] - prices[i-1]) / prices[i-1] 
                  for i in range(1, len(prices)) if prices[i-1] > 0]
        
        if len(returns) > 1:
            self.params['volatility'] = np.std(returns)
    
    def _calculate_grid_prices(self, center: float, levels: int, 
                              range_pct: float) -> Tuple[List[float], List[float]]:
        """Calculate grid prices based on mode (geometric or linear)."""
        if self.params.get('grid_mode') == 'geometric':
            return self._calculate_geometric_prices(center, levels, range_pct)
        else:
            return self._calculate_linear_prices(center, levels, range_pct)
    
    def _calculate_geometric_prices(self, center: float, levels: int, 
                                   range_pct: float) -> Tuple[List[float], List[float]]:
        """Calculate geometric grid prices with percentage-based intervals."""
        GLOBAL_STATE.grid_metrics['geometric_grids_used'] += 1
        
        ratio = (1 + range_pct/100) ** (1/levels)
        
        buy_prices = [center * (1/ratio) ** i for i in range(1, levels + 1)]
        sell_prices = [center * ratio ** i for i in range(1, levels + 1)]
        
        return buy_prices, sell_prices
    
    def _calculate_linear_prices(self, center: float, levels: int, 
                                range_pct: float) -> Tuple[List[float], List[float]]:
        """Calculate linear grid prices with equal price intervals."""
        price_range = center * range_pct / 100
        step_size = price_range / levels
        
        buy_prices = [center - (step_size * i) for i in range(1, levels + 1) 
                     if center - (step_size * i) > 0]
        sell_prices = [center + (step_size * i) for i in range(1, levels + 1)]
        
        return buy_prices, sell_prices
    
    def _setup_enhanced_grid(self, current_price: float) -> None:
        """Setup high-density grid with enhanced features."""
        if not GRID_CONFIG['enable_trading']:
            logger.info(f"Trading disabled, skipping grid setup for {self.symbol}")
            return
            
        logger.info(f"Setting up enhanced grid for {self.symbol} at ${current_price:.4f}")
        
        self.cancel_all_orders()
        self.grid_center = current_price
        self.last_update = time.time()
        
        if self.symbol not in EXCHANGE_INFO['symbols']:
            logger.error(f"No exchange info for {self.symbol}")
            return
        
        base_asset = EXCHANGE_INFO['symbols'][self.symbol]['baseAsset']
        grid_levels = self.params['grid_levels']
        grid_range = self.params['grid_range_percent']
        
        logger.info(f"Grid params: {grid_levels} levels, ±{grid_range:.1f}% range, "
                   f"{self.params.get('grid_mode', 'geometric')} spacing")
        
        buy_prices, sell_prices = self._calculate_grid_prices(current_price, grid_levels, grid_range)
        
        if GRID_CONFIG['check_liquidity']:
            buy_prices = self._adjust_prices_for_liquidity(buy_prices, 'BUY')
            sell_prices = self._adjust_prices_for_liquidity(sell_prices, 'SELL')
        
        available_usdt = capital_manager.get_available('USDT')
        available_base = capital_manager.get_available(base_asset)
        
        if available_usdt <= 0 and available_base <= 0:
            logger.warning(f"No available balance for grid trading {self.symbol}")
            return
        
        orders_placed = self._place_grid_orders(buy_prices, sell_prices, 
                                              available_usdt, available_base, base_asset)
        
        self.active = True
        efficiency = (orders_placed / (grid_levels * 2)) * 100
        logger.info(f"✅ Enhanced grid setup complete for {self.symbol}: "
                   f"{orders_placed} orders placed (efficiency: {efficiency:.1f}%)")
    
    def _adjust_prices_for_liquidity(self, prices: List[float], side: str) -> List[float]:
        """Adjust grid prices based on order book liquidity."""
        order_book = self.api.get_order_book(self.symbol, limit=100)
        if not order_book:
            return prices
        
        adjusted_prices = []
        
        for price in prices:
            if side == 'BUY':
                nearby_bids = [float(bid[0]) for bid in order_book.get('bids', []) 
                              if abs(float(bid[0]) - price) / price < 0.001]
                adjusted_prices.append(max(nearby_bids) if nearby_bids else price)
            else:
                nearby_asks = [float(ask[0]) for ask in order_book.get('asks', []) 
                              if abs(float(ask[0]) - price) / price < 0.001]
                adjusted_prices.append(min(nearby_asks) if nearby_asks else price)
        
        return adjusted_prices
    
    def _place_grid_orders(self, buy_prices: List[float], sell_prices: List[float],
                          available_usdt: float, available_base: float, 
                          base_asset: str) -> int:
        """Place all grid orders with proper capital management."""
        total_balance = GLOBAL_STATE.account['total_balance_usdt']
        allocation_per_symbol = total_balance * GRID_CONFIG['allocation_per_symbol']
        order_size_pct = self.params.get('order_size_percent', GRID_CONFIG['base_order_size_percent'])
        min_order_value = self.params['min_order_value']
        
        order_size_usdt = max(allocation_per_symbol * order_size_pct, min_order_value)
        
        orders_placed = 0
        
        # Place sell orders first
        for i, sell_price in enumerate(sell_prices):
            sell_quantity = order_size_usdt / sell_price
            
            if sell_quantity <= available_base and capital_manager.reserve(base_asset, sell_quantity):
                sell_order = self._place_grid_order('SELL', sell_price, sell_quantity, i + 1)
                if sell_order:
                    self.grid_orders['sell'].append(sell_order)
                    orders_placed += 1
                    available_base -= sell_quantity
                else:
                    capital_manager.release(base_asset, sell_quantity)
            
            if orders_placed % 10 == 0 and orders_placed > 0:
                time.sleep(1)  # Rate limiting
        
        # Place buy orders
        for i, buy_price in enumerate(buy_prices):
            buy_quantity = order_size_usdt / buy_price
            buy_cost = buy_quantity * buy_price
            
            if buy_cost <= available_usdt and capital_manager.reserve('USDT', buy_cost):
                buy_order = self._place_grid_order('BUY', buy_price, buy_quantity, i + 1)
                if buy_order:
                    self.grid_orders['buy'].append(buy_order)
                    orders_placed += 1
                    available_usdt -= buy_cost
                else:
                    capital_manager.release('USDT', buy_cost)
            
            if orders_placed % 10 == 0 and orders_placed > 0:
                time.sleep(1)  # Rate limiting
        
        return orders_placed
    
    def _place_grid_order(self, side: str, price: float, quantity: float, level: int) -> Optional[Dict]:
        """Place a single grid order with comprehensive validation."""
        try:
            params = {
                'symbol': self.symbol,
                'side': side,
                'type': 'LIMIT',
                'timeInForce': 'GTC',
                'price': str(price),
                'quantity': str(quantity)
            }
            
            order = self.api.place_order(**params)
            
            if order:
                grid_order_info = {
                    'orderId': order['orderId'],
                    'symbol': self.symbol,
                    'side': side,
                    'price': price,
                    'quantity': quantity,
                    'grid_level': level,
                    'status': order.get('status', 'NEW'),
                    'time': order.get('transactTime', int(time.time() * 1000)),
                    'filled_qty': 0
                }
                
                self.order_map[order['orderId']] = level
                
                if self.symbol not in GLOBAL_STATE.grid_orders:
                    GLOBAL_STATE.grid_orders[self.symbol] = []
                GLOBAL_STATE.grid_orders[self.symbol].append(grid_order_info)
                
                activity_queue.put({
                    'type': 'grid_order',
                    'symbol': self.symbol,
                    'side': side,
                    'price': price,
                    'quantity': quantity,
                    'status': order.get('status', 'NEW'),
                    'grid_level': level,
                    'time': order.get('transactTime', int(time.time() * 1000))
                })
                
                return order
                
        except Exception as e:
            logger.error(f"Failed to place {side} order for {self.symbol}: {e}")
            
        return None
    
    def _check_filled_orders(self) -> None:
        """Check for filled orders and manage replacements."""
        if not self.active:
            return
            
        open_orders = self.api.get_open_orders(self.symbol)
        if open_orders is None:
            return
            
        open_order_ids = {o['orderId'] for o in open_orders}
        filled_count = 0
        
        for side in ['buy', 'sell']:
            for order in self.grid_orders[side]:
                if (order['orderId'] not in open_order_ids and 
                    order['orderId'] not in self.filled_orders):
                    
                    self.filled_orders.add(order['orderId'])
                    filled_count += 1
                    
                    self._release_order_capital(order)
                    self._add_fill_activity(order)
                    self._place_replacement_order(order)
        
        if filled_count > 0:
            logger.info(f"📈 {filled_count} grid orders filled for {self.symbol}")
    
    def _release_order_capital(self, order: Dict) -> None:
        """Release capital for a filled order."""
        if order['side'] == 'BUY':
            capital_manager.release('USDT', order['price'] * order['quantity'])
        else:
            base_asset = EXCHANGE_INFO['symbols'][self.symbol]['baseAsset']
            capital_manager.release(base_asset, order['quantity'])
    
    def _add_fill_activity(self, order: Dict) -> None:
        """Add fill activity to queue."""
        activity_queue.put({
            'type': 'grid_filled',
            'symbol': self.symbol,
            'side': order['side'],
            'price': order['price'],
            'quantity': order['quantity'],
            'grid_level': order['grid_level'],
            'time': int(time.time() * 1000)
        })
    
    def _place_replacement_order(self, filled_order: Dict) -> None:
        """Place replacement order on opposite side."""
        current_price = GLOBAL_STATE.market_prices.get(self.symbol, 0)
        if current_price == 0:
            return
        
        base_asset = EXCHANGE_INFO['symbols'][self.symbol]['baseAsset']
        
        if filled_order['side'] == 'BUY':
            new_side = 'SELL'
            new_price = current_price * 1.005  # 0.5% above current
            new_quantity = filled_order['quantity']
            
            if capital_manager.reserve(base_asset, new_quantity):
                new_order = self._place_grid_order(new_side, new_price, new_quantity, 
                                                 filled_order['grid_level'])
                if not new_order:
                    capital_manager.release(base_asset, new_quantity)
        else:
            new_side = 'BUY'
            new_price = current_price * 0.995  # 0.5% below current
            new_quantity = filled_order['quantity']
            cost = new_price * new_quantity
            
            if capital_manager.reserve('USDT', cost):
                new_order = self._place_grid_order(new_side, new_price, new_quantity, 
                                                 filled_order['grid_level'])
                if not new_order:
                    capital_manager.release('USDT', cost)
    
    def _handle_partial_fills(self) -> None:
        """Handle partial fills efficiently."""
        if not self.active:
            return
        
        open_orders = self.api.get_open_orders(self.symbol)
        if not open_orders:
            return
        
        base_asset = EXCHANGE_INFO['symbols'][self.symbol]['baseAsset']
        
        for open_order in open_orders:
            order_id = open_order['orderId']
            if order_id not in self.order_map:
                continue
            
            orig_qty = float(open_order['origQty'])
            executed_qty = float(open_order['executedQty'])
            
            if executed_qty > 0 and executed_qty / orig_qty >= 0.3:
                if order_id not in self.partial_fills:
                    self.partial_fills[order_id] = executed_qty
                    GLOBAL_STATE.grid_metrics['partial_fills_handled'] += 1
                    
                    self._handle_partial_fill_replacement(open_order, executed_qty, base_asset)
                    
                    logger.info(f"🔄 Partial fill handled for {self.symbol}: "
                               f"{executed_qty:.6f} of {orig_qty:.6f}")
    
    def _handle_partial_fill_replacement(self, open_order: Dict, executed_qty: float, 
                                        base_asset: str) -> None:
        """Handle replacement for partial fills."""
        side = open_order['side']
        price = float(open_order['price'])
        order_id = open_order['orderId']
        
        if side == 'BUY':
            new_side = 'SELL'
            new_price = price * 1.01
            new_quantity = executed_qty
            
            if capital_manager.reserve(base_asset, new_quantity):
                replacement_order = self._place_grid_order(new_side, new_price, new_quantity, 
                                                         self.order_map[order_id])
                if not replacement_order:
                    capital_manager.release(base_asset, new_quantity)
        else:
            new_side = 'BUY'
            new_price = price * 0.99
            new_quantity = executed_qty
            cost = new_price * new_quantity
            
            if capital_manager.reserve('USDT', cost):
                replacement_order = self._place_grid_order(new_side, new_price, new_quantity, 
                                                         self.order_map[order_id])
                if not replacement_order:
                    capital_manager.release('USDT', cost)
    
    def cancel_all_orders(self) -> None:
        """Cancel all grid orders and release reserved capital."""
        canceled = 0
        
        open_orders = self.api.get_open_orders(self.symbol)
        if open_orders:
            base_asset = EXCHANGE_INFO['symbols'][self.symbol]['baseAsset']
            
            for order in open_orders:
                if order['orderId'] in self.order_map:
                    try:
                        result = self.api.cancel_order(self.symbol, order['orderId'])
                        if result:
                            canceled += 1
                            self._release_canceled_order_capital(order, base_asset)
                    except Exception as e:
                        logger.error(f"Failed to cancel order {order['orderId']}: {e}")
        
        self._reset_grid_state()
        
        if canceled > 0:
            logger.info(f"Canceled {canceled} orders for {self.symbol}")
    
    def _release_canceled_order_capital(self, order: Dict, base_asset: str) -> None:
        """Release capital for canceled orders."""
        if order['side'] == 'BUY':
            capital_manager.release('USDT', float(order['price']) * float(order['origQty']))
        else:
            capital_manager.release(base_asset, float(order['origQty']))
    
    def _reset_grid_state(self) -> None:
        """Reset grid state."""
        self.grid_orders = {'buy': [], 'sell': []}
        self.order_map.clear()
        self.filled_orders.clear()
        self.partial_fills.clear()
        self.active = False
    
    def get_state(self) -> Dict:
        """Get current grid state with real-time data."""
        current_price = GLOBAL_STATE.market_prices.get(self.symbol, 0)
        
        buy_orders = len([o for o in self.grid_orders['buy'] 
                         if o['orderId'] not in self.filled_orders])
        sell_orders = len([o for o in self.grid_orders['sell'] 
                          if o['orderId'] not in self.filled_orders])
        
        market_data = GLOBAL_STATE.market_24hr.get(self.symbol, {})
        
        return {
            'symbol': self.symbol,
            'active': self.active,
            'current_price': current_price,
            'grid_center': self.grid_center,
            'volatility': self.params['volatility'] * 100,
            'atr': self.params.get('atr', 0),
            'atr_pct': self.params.get('atr_pct', 0) * 100,
            'grid_levels': self.params['grid_levels'],
            'grid_range': self.params['grid_range_percent'],
            'grid_mode': self.params.get('grid_mode', 'geometric'),
            'rebalance_threshold': self.params.get('rebalance_threshold', 0.02) * 100,
            'buy_orders': buy_orders,
            'sell_orders': sell_orders,
            'total_orders': buy_orders + sell_orders,
            'filled_orders': len(self.filled_orders),
            'partial_fills': len(self.partial_fills),
            'liquidity_score': self.params.get('liquidity_score', 1.0),
            'last_update': self.last_update,
            'price_change_24h': market_data.get('priceChangePercent', 0),
            'volume_24h': market_data.get('quoteVolume', 0)
        }

# ============================================================================
# GRID TRADING ENGINE
# ============================================================================

class GridTradingEngine:
    """Enhanced grid trading engine coordinator."""
    
    def __init__(self, api: BinanceAPI, trading_engine: TradingEngine, 
                 market_analyzer: MarketAnalyzer):
        self.api = api
        self.trading_engine = trading_engine
        self.market_analyzer = market_analyzer
        self.running = False
        self.grids: Dict[str, EnhancedGridManager] = {}
        
    def start(self) -> None:
        """Start grid trading with selected symbols."""
        self.running = True
        
        selected_symbols = GRID_CONFIG['symbols']
        GLOBAL_STATE.selected_symbols = selected_symbols
        
        # Initialize grids
        for symbol in selected_symbols:
            params = self.market_analyzer.calculate_dynamic_grid_params(symbol)
            self.grids[symbol] = EnhancedGridManager(symbol, self.api, 
                                                   self.trading_engine, params)
        
        # Start threads
        self.update_thread = threading.Thread(target=self._update_loop, daemon=True)
        self.update_thread.start()
        
        self.price_thread = threading.Thread(target=self._price_monitor_loop, daemon=True)
        self.price_thread.start()
        
        logger.info(f"🚀 Enhanced grid trading started for {len(selected_symbols)} symbols: "
                   f"{', '.join(selected_symbols)}")
        logger.info(f"📊 Grid density: {GRID_CONFIG['min_grid_levels']}-"
                   f"{GRID_CONFIG['max_grid_levels']} levels")
    
    def stop(self) -> None:
        """Stop grid trading."""
        self.running = False
        
        for grid in self.grids.values():
            grid.cancel_all_orders()
        
        logger.info("Grid trading stopped")
    
    def _update_loop(self) -> None:
        """Main update loop for grid management."""
        while self.running:
            try:
                self.trading_engine.update_market_prices()
                self.trading_engine.update_24hr_stats()
                self.trading_engine.update_account_balances()
                
                GLOBAL_STATE.performance['uptime'] = time.time() - GLOBAL_STATE.performance['start_time']
                
                for symbol, grid in self.grids.items():
                    try:
                        grid.update()
                        GLOBAL_STATE.grid_states[symbol] = grid.get_state()
                    except Exception as e:
                        logger.error(f"Error updating grid for {symbol}: {e}")
                
                self.trading_engine.sync_trades_history()
                
                time.sleep(GRID_CONFIG['update_interval'])
                
            except Exception as e:
                logger.error(f"Grid update loop error: {e}")
                time.sleep(30)
    
    def _price_monitor_loop(self) -> None:
        """Monitor prices for grid adjustments."""
        while self.running:
            try:
                self.trading_engine.update_market_prices()
                
                for grid in self.grids.values():
                    grid.check_price_movement()
                
                time.sleep(GRID_CONFIG['price_check_interval'])
                
            except Exception as e:
                logger.error(f"Price monitor error: {e}")
                time.sleep(10)

# ============================================================================
# WEBSOCKET MANAGER
# ============================================================================

class WebSocketManager:
    """WebSocket manager for real-time data."""
    
    def __init__(self, api: BinanceAPI, trading_engine: TradingEngine):
        self.api = api
        self.trading_engine = trading_engine
        self.ws = None
        self.running = False
        self.listen_key = None
        
    def start(self) -> None:
        """Start WebSocket connection."""
        self.running = True
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
    
    def stop(self) -> None:
        """Stop WebSocket connection."""
        self.running = False
        if self.ws:
            self.ws.close()
    
    def _run(self) -> None:
        """Run WebSocket connection with proper error handling."""
        self.listen_key = self.api.get_listen_key()
        if not self.listen_key:
            logger.error("Failed to get listen key")
            return
        
        def on_message(ws, message):
            try:
                data = json.loads(message)
                GLOBAL_STATE.performance['websocket_messages'] += 1
                self._process_message(data)
            except Exception as e:
                logger.error(f"WebSocket message error: {e}")
        
        def on_error(ws, error):
            logger.error(f"WebSocket error: {error}")
            GLOBAL_STATE.performance['errors'] += 1
        
        def on_close(ws, close_status_code, close_msg):
            logger.info("WebSocket closed")
            if self.running:
                time.sleep(5)
                self._run()  # Reconnect
        
        def on_open(ws):
            logger.info("WebSocket connected")
            GLOBAL_STATE.status = 'connected'
        
        # Construct WebSocket URL
        if self.api.endpoint.get('is_testnet', False):
            ws_url = f"wss://stream.testnet.binance.vision:9443/ws/{self.listen_key}"
        else:
            ws_url = f"wss://stream.binance.com:9443/ws/{self.listen_key}"
        
        logger.info(f"Connecting to WebSocket: {ws_url}")
        
        self.ws = websocket.WebSocketApp(
            ws_url,
            on_message=on_message,
            on_error=on_error,
            on_close=on_close,
            on_open=on_open
        )
        
        # Start keep alive thread
        keep_alive_thread = threading.Thread(target=self._keep_alive, daemon=True)
        keep_alive_thread.start()
        
        self.ws.run_forever()
    
    def _process_message(self, data: Dict) -> None:
        """Process different WebSocket message types."""
        event_type = data.get('e')
        
        if event_type == 'executionReport':
            self._process_order_update(data)
        elif event_type == 'outboundAccountPosition':
            self.trading_engine.update_account_balances()
        elif event_type == 'balanceUpdate':
            self.trading_engine.update_account_balances()
    
    def _process_order_update(self, data: Dict) -> None:
        """Process order execution updates."""
        symbol = data['s']
        order_id = data['i']
        status = data['X']
        order_type = data['o']
        
        # Update grid orders status
        if symbol in GLOBAL_STATE.grid_orders:
            for order in GLOBAL_STATE.grid_orders[symbol]:
                if order['orderId'] == order_id:
                    order['status'] = status
                    if 'filled_qty' in order:
                        order['filled_qty'] = float(data.get('z', 0))
                    break
        
        # Handle different order statuses
        if status == 'FILLED':
            self._handle_filled_order(data, order_type)
        elif status == 'PARTIALLY_FILLED':
            self._handle_partial_fill(data)
        elif status == 'CANCELED':
            logger.info(f"Order CANCELED: {order_id} for {symbol}")
        elif status == 'REJECTED':
            logger.warning(f"Order REJECTED: {order_id} for {symbol} - "
                          f"{data.get('r', 'Unknown reason')}")
            GLOBAL_STATE.performance['errors'] += 1
    
    def _handle_filled_order(self, data: Dict, order_type: str) -> None:
        """Handle filled order."""
        GLOBAL_STATE.performance['orders_filled'] += 1
        
        activity_queue.put({
            'type': 'trade',
            'symbol': data['s'],
            'side': data['S'],
            'price': float(data['L']),
            'quantity': float(data['l']),
            'order_type': order_type,
            'commission': float(data.get('n', 0)),
            'commission_asset': data.get('N', ''),
            'time': data['E']
        })
        
        logger.info(f"🎯 Order FILLED: {data['S']} {data['l']} {data['s']} @ {data['L']}")
        
        # Trigger trade sync
        threading.Thread(target=self.trading_engine.sync_trades_history, daemon=True).start()
    
    def _handle_partial_fill(self, data: Dict) -> None:
        """Handle partial fill."""
        logger.info(f"🔄 Order PARTIALLY FILLED: {data['S']} {data['l']} {data['s']} @ {data['L']} "
                   f"(Total: {data['z']}/{data['q']})")
    
    def _keep_alive(self) -> None:
        """Keep listen key alive."""
        while self.running:
            time.sleep(1800)  # 30 minutes
            if self.listen_key:
                if self.api.keepalive_listen_key(self.listen_key):
                    logger.info("Listen key renewed")
                else:
                    logger.error("Failed to renew listen key")
                    self.listen_key = self.api.get_listen_key()

# ============================================================================
# WEB INTERFACE
# ============================================================================

class HTTPRequestHandler(BaseHTTPRequestHandler):
    """HTTP request handler for web interface."""
    
    def do_GET(self):
        """Handle GET requests."""
        if self.path == '/':
            self._serve_html()
        elif self.path == '/api/data':
            self._serve_data()
    
    def do_POST(self):
        """Handle POST requests."""
        if self.path == '/api/connect':
            self._handle_connect()
        elif self.path == '/api/toggle_grid':
            self._handle_toggle_grid()
        elif self.path == '/api/emergency_stop':
            self._handle_emergency_stop()
    
    def _serve_html(self):
        """Serve the main HTML interface."""
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()
        self.wfile.write(HTML_CONTENT.encode())
    
    def _serve_data(self):
        """Serve API data."""
        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        
        response = {
            'status': GLOBAL_STATE.status,
            'endpoint': GLOBAL_STATE.endpoint,
            'account': GLOBAL_STATE.account,
            'market_prices': GLOBAL_STATE.market_prices,
            'market_24hr': GLOBAL_STATE.market_24hr,
            'activities': list(GLOBAL_STATE.activities)[-100:],
            'open_orders': GLOBAL_STATE.open_orders,
            'positions': GLOBAL_STATE.positions,
            'grid_states': GLOBAL_STATE.grid_states,
            'grid_orders': GLOBAL_STATE.grid_orders,
            'stats': GLOBAL_STATE.stats,
            'performance': GLOBAL_STATE.performance,
            'selected_cryptos': GLOBAL_STATE.selected_symbols,
            'grid_config': {
                'enabled': GRID_CONFIG['enable_trading'],
                'levels': f"{GRID_CONFIG['min_grid_levels']}-{GRID_CONFIG['max_grid_levels']}",
                'range': f"{GRID_CONFIG['base_grid_range']}-{GRID_CONFIG['max_grid_range']}%"
            },
            'market_analysis': MARKET_ANALYSIS,
            'capital_allocation': GLOBAL_STATE.capital_allocation,
            'grid_metrics': GLOBAL_STATE.grid_metrics
        }
        
        self.wfile.write(json.dumps(response).encode())
    
    def _handle_connect(self):
        """Handle connection request."""
        content_length = int(self.headers['Content-Length'])
        post_data = self.rfile.read(content_length)
        data = json.loads(post_data.decode())
        
        global api, trading_engine, market_analyzer, grid_engine, ws_manager
        
        api_key = data.get('apiKey', '')
        secret_key = data.get('secretKey', '')
        endpoint_index = int(data.get('endpoint', 0))
        
        global API_KEY, SECRET_KEY
        API_KEY = api_key
        SECRET_KEY = secret_key
        
        success = False
        if endpoint_index < len(ENDPOINTS):
            api = BinanceAPI(api_key, secret_key)
            endpoint = ENDPOINTS[endpoint_index]
            
            if api.set_endpoint(endpoint):
                GLOBAL_STATE.endpoint = endpoint
                GLOBAL_STATE.status = 'connected'
                
                # Initialize components
                trading_engine = TradingEngine(api)
                market_analyzer = MarketAnalyzer(api)
                
                # Get initial data
                trading_engine.update_market_prices()
                trading_engine.update_account_balances()
                trading_engine.update_24hr_stats()
                trading_engine.sync_trades_history()
                
                # Start enhanced grid trading
                grid_engine = GridTradingEngine(api, trading_engine, market_analyzer)
                grid_engine.start()
                
                # Start WebSocket
                ws_manager = WebSocketManager(api, trading_engine)
                ws_manager.start()
                
                # Start update loop
                update_thread = threading.Thread(target=update_loop, daemon=True)
                update_thread.start()
                
                success = True
                logger.info(f"✅ Connected to {endpoint['name']} with enhanced grid system")
        
        self._send_json_response({'success': success})
    
    def _handle_toggle_grid(self):
        """Handle grid toggle request."""
        content_length = int(self.headers['Content-Length'])
        post_data = self.rfile.read(content_length)
        data = json.loads(post_data.decode())
        
        GRID_CONFIG['enable_trading'] = data.get('active', True)
        
        if grid_engine:
            if GRID_CONFIG['enable_trading']:
                grid_engine.start()
            else:
                grid_engine.stop()
        
        self._send_json_response({'success': True})
    
    def _handle_emergency_stop(self):
        """Handle emergency stop request."""
        GRID_CONFIG['enable_trading'] = False
        
        if grid_engine:
            grid_engine.stop()
        
        if ws_manager:
            ws_manager.stop()
        
        GLOBAL_STATE.status = 'stopped'
        self._send_json_response({'success': True})
    
    def _send_json_response(self, data: Dict):
        """Send JSON response."""
        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())
    
    def log_message(self, format, *args):
        """Suppress HTTP logs."""
        return

# ============================================================================
# GLOBAL INSTANCES AND MAIN LOOP
# ============================================================================

# Global instances
api = None
trading_engine = None
market_analyzer = None
grid_engine = None
ws_manager = None

def update_loop() -> None:
    """Main update loop for real-time data."""
    while GLOBAL_STATE.status == 'connected':
        try:
            if trading_engine:
                trading_engine.update_market_prices()
                trading_engine.update_account_balances()
            
            # Update open orders
            if api:
                all_orders = []
                for symbol in GRID_CONFIG['symbols']:
                    orders = api.get_open_orders(symbol)
                    if orders:
                        all_orders.extend(orders)
                GLOBAL_STATE.open_orders = {o['orderId']: o for o in all_orders}
            
            # Process activity queue
            while not activity_queue.empty():
                try:
                    activity = activity_queue.get_nowait()
                    activity['timestamp'] = datetime.fromtimestamp(
                        activity.get('time', 0) / 1000).isoformat()
                    GLOBAL_STATE.activities.append(activity)
                except:
                    break
            
            # Periodic market analysis
            if (market_analyzer and 
                time.time() - MARKET_ANALYSIS.get('last_update', 0) > 3600):
                logger.info("Running periodic market analysis...")
                new_symbols = market_analyzer.analyze_market()
                if new_symbols != GLOBAL_STATE.selected_symbols:
                    logger.info("Market conditions changed, updating selected symbols...")
            
        except Exception as e:
            logger.error(f"Update loop error: {e}")
            GLOBAL_STATE.performance['errors'] += 1
        
        time.sleep(5)

# ============================================================================
# STATE MANAGEMENT
# ============================================================================

def save_state() -> None:
    """Save current state to file."""
    state = {
        'executed_trades': GLOBAL_STATE.executed_trades,
        'positions': GLOBAL_STATE.positions,
        'stats': GLOBAL_STATE.stats,
        'selected_symbols': GLOBAL_STATE.selected_symbols,
        'grid_metrics': GLOBAL_STATE.grid_metrics,
        'timestamp': datetime.now().isoformat()
    }
    
    try:
        with open(GRID_CONFIG['state_file'], 'w') as f:
            json.dump(state, f, indent=2)
        logger.info("State saved successfully")
        logger.info(f"📊 Final metrics: {GLOBAL_STATE.grid_metrics}")
    except Exception as e:
        logger.error(f"Failed to save state: {e}")

def load_state() -> None:
    """Load previous state on startup."""
    try:
        if os.path.exists(GRID_CONFIG['state_file']):
            with open(GRID_CONFIG['state_file'], 'r') as f:
                state = json.load(f)
                if 'grid_metrics' in state:
                    GLOBAL_STATE.grid_metrics.update(state['grid_metrics'])
                logger.info(f"Previous state loaded from {state.get('timestamp', 'unknown time')}")
    except Exception as e:
        logger.error(f"Error loading state: {e}")

def cleanup(*args) -> None:
    """Cleanup on exit."""
    logger.info("Shutting down...")
    
    if grid_engine:
        grid_engine.stop()
    
    if ws_manager:
        ws_manager.stop()
    
    save_state()
    sys.exit(0)

# Register signal handlers
signal.signal(signal.SIGINT, cleanup)
signal.signal(signal.SIGTERM, cleanup)

# ============================================================================
# HTML CONTENT
# ============================================================================

HTML_CONTENT = '''
<!DOCTYPE html>
<html>
<head>
    <title>Enhanced Grid Trading Bot V6 - High-Density Dynamic Grids</title>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        :root {
            --bg-primary: #0b0e11;
            --bg-secondary: #181a20;
            --bg-tertiary: #2b3139;
            --text-primary: #eaecef;
            --text-secondary: #848e9c;
            --accent: #f0b90b;
            --accent-hover: #d4a20a;
            --success: #0ecb81;
            --danger: #f6465d;
            --info: #3861fb;
            --warning: #ffa800;
            --border: #3a424d;
        }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: var(--bg-primary);
            color: var(--text-primary);
            line-height: 1.6;
        }
        
        /* Header */
        .header {
            background: linear-gradient(180deg, var(--bg-secondary) 0%, rgba(24, 26, 32, 0.95) 100%);
            border-bottom: 2px solid var(--accent);
            position: sticky;
            top: 0;
            z-index: 1000;
            backdrop-filter: blur(10px);
        }
        
        .header-content {
            max-width: 1600px;
            margin: 0 auto;
            padding: 16px 24px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 16px;
        }
        
        .logo {
            font-size: 24px;
            font-weight: 700;
            color: var(--accent);
            display: flex;
            align-items: center;
            gap: 12px;
        }
        
        .version-badge {
            background: linear-gradient(90deg, var(--success) 0%, var(--info) 100%);
            color: white;
            padding: 4px 8px;
            border-radius: 12px;
            font-size: 12px;
            font-weight: 600;
        }
        
        .trading-status {
            display: flex;
            align-items: center;
            gap: 8px;
            padding: 8px 16px;
            background: rgba(14, 203, 129, 0.1);
            border: 1px solid rgba(14, 203, 129, 0.3);
            border-radius: 8px;
        }
        
        .trading-status.inactive {
            background: rgba(246, 70, 93, 0.1);
            border-color: rgba(246, 70, 93, 0.3);
        }
        
        .status-dot {
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background: var(--success);
            animation: pulse 2s infinite;
        }
        
        .trading-status.inactive .status-dot {
            background: var(--danger);
        }
        
        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.5; }
        }
        
        .balance-display {
            background: linear-gradient(90deg, rgba(14, 203, 129, 0.1) 0%, rgba(14, 203, 129, 0.05) 100%);
            padding: 12px 20px;
            border-radius: 8px;
            border: 1px solid rgba(14, 203, 129, 0.3);
        }
        
        .balance-label {
            font-size: 12px;
            color: var(--text-secondary);
            text-transform: uppercase;
        }
        
        .balance-value {
            font-size: 24px;
            font-weight: 700;
            color: var(--success);
        }
        
        /* Enhanced Trading Stats Bar */
        .trading-stats-bar {
            background: var(--bg-secondary);
            border-bottom: 1px solid var(--border);
            padding: 16px 0;
        }
        
        .trading-stats {
            max-width: 1600px;
            margin: 0 auto;
            padding: 0 24px;
            display: flex;
            justify-content: space-around;
            flex-wrap: wrap;
            gap: 24px;
        }
        
        .stat-item {
            text-align: center;
        }
        
        .stat-label {
            font-size: 12px;
            color: var(--text-secondary);
            text-transform: uppercase;
            margin-bottom: 4px;
        }
        
        .stat-value {
            font-size: 20px;
            font-weight: 700;
        }
        
        .stat-value.positive {
            color: var(--success);
        }
        
        .stat-value.negative {
            color: var(--danger);
        }
        
        .stat-value.enhanced {
            color: var(--accent);
        }
        
        /* Login */
        .login-container {
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 20px;
            background: radial-gradient(circle at center, rgba(240, 185, 11, 0.1) 0%, transparent 70%);
        }
        
        .login-card {
            background: var(--bg-secondary);
            padding: 48px;
            border-radius: 16px;
            width: 100%;
            max-width: 480px;
            box-shadow: 0 20px 60px rgba(0, 0, 0, 0.5);
            border: 1px solid var(--border);
        }
        
        .enhanced-title {
            background: linear-gradient(90deg, var(--accent) 0%, var(--success) 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
            font-weight: 800;
        }
        
        .form-group {
            margin-bottom: 24px;
        }
        
        .form-group label {
            display: block;
            margin-bottom: 8px;
            color: var(--text-secondary);
            font-size: 14px;
            font-weight: 500;
        }
        
        .form-input, .form-select {
            width: 100%;
            padding: 14px 16px;
            background: var(--bg-tertiary);
            border: 1px solid var(--border);
            color: var(--text-primary);
            border-radius: 8px;
            font-size: 16px;
            transition: all 0.3s;
        }
        
        .form-input:focus, .form-select:focus {
            outline: none;
            border-color: var(--accent);
            box-shadow: 0 0 0 3px rgba(240, 185, 11, 0.1);
        }
        
        .btn {
            width: 100%;
            padding: 14px;
            background: linear-gradient(90deg, var(--accent) 0%, #ffdc4e 100%);
            color: var(--bg-primary);
            border: none;
            border-radius: 8px;
            font-size: 16px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.3s;
        }
        
        .btn:hover:not(:disabled) {
            transform: translateY(-2px);
            box-shadow: 0 8px 24px rgba(240, 185, 11, 0.4);
        }
        
        .btn:disabled {
            opacity: 0.6;
            cursor: not-allowed;
        }
        
        /* Dashboard */
        .dashboard {
            display: none;
            max-width: 1600px;
            margin: 0 auto;
            padding: 24px;
        }
        
        /* Enhanced Grid Overview */
        .grid-overview {
            background: linear-gradient(135deg, rgba(240, 185, 11, 0.1) 0%, rgba(240, 185, 11, 0.02) 100%);
            border: 2px solid rgba(240, 185, 11, 0.3);
            border-radius: 16px;
            padding: 24px;
            margin-bottom: 24px;
        }
        
        .grid-overview-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 24px;
        }
        
        .grid-overview-title {
            font-size: 24px;
            font-weight: 700;
            display: flex;
            align-items: center;
            gap: 12px;
        }
        
        .enhanced-badge {
            background: linear-gradient(90deg, var(--success) 0%, var(--info) 100%);
            color: white;
            padding: 6px 12px;
            border-radius: 20px;
            font-size: 12px;
            font-weight: 600;
        }
        
        .grid-controls {
            display: flex;
            gap: 12px;
        }
        
        .btn-sm {
            padding: 8px 16px;
            font-size: 14px;
            width: auto;
        }
        
        .btn-toggle {
            background: var(--success);
        }
        
        .btn-toggle.inactive {
            background: var(--danger);
        }
        
        /* Enhanced Grid Cards */
        .grid-cards {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
            gap: 20px;
            margin-bottom: 24px;
        }
        
        .grid-card {
            background: var(--bg-secondary);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 20px;
            transition: all 0.3s;
        }
        
        .grid-card:hover {
            transform: translateY(-2px);
            box-shadow: 0 8px 24px rgba(0, 0, 0, 0.2);
            border-color: var(--accent);
        }
        
        .grid-card.active {
            border-color: var(--success);
            box-shadow: 0 0 20px rgba(14, 203, 129, 0.1);
        }
        
        .grid-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 16px;
        }
        
        .grid-symbol {
            font-size: 18px;
            font-weight: 600;
        }
        
        .grid-status {
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 12px;
            font-weight: 600;
            background: var(--success);
            color: var(--bg-primary);
        }
        
        .grid-status.inactive {
            background: var(--text-secondary);
        }
        
        .grid-info {
            display: grid;
            gap: 12px;
            font-size: 14px;
        }
        
        .grid-info-row {
            display: flex;
            justify-content: space-between;
        }
        
        .grid-info-label {
            color: var(--text-secondary);
        }
        
        .enhanced-metric {
            color: var(--accent);
            font-weight: 600;
        }
        
        .grid-orders-summary {
            display: flex;
            justify-content: space-between;
            margin-top: 16px;
            padding-top: 16px;
            border-top: 1px solid var(--border);
        }
        
        .order-count {
            text-align: center;
        }
        
        .order-count-value {
            font-size: 24px;
            font-weight: 700;
            display: block;
        }
        
        .order-count-label {
            font-size: 12px;
            color: var(--text-secondary);
            text-transform: uppercase;
        }
        
        /* Activity Feed */
        .activity-container {
            background: var(--bg-secondary);
            border-radius: 12px;
            padding: 24px;
            max-height: 600px;
            overflow-y: auto;
        }
        
        .activity-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 20px;
            padding-bottom: 16px;
            border-bottom: 1px solid var(--border);
        }
        
        .activity-title {
            font-size: 20px;
            font-weight: 600;
            display: flex;
            align-items: center;
            gap: 12px;
        }
        
        .live-dot {
            width: 8px;
            height: 8px;
            background: var(--danger);
            border-radius: 50%;
            animation: pulse 1s infinite;
        }
        
        .activity-list {
            display: flex;
            flex-direction: column;
            gap: 8px;
        }
        
        .activity-item {
            background: var(--bg-tertiary);
            border-radius: 8px;
            padding: 16px;
            display: flex;
            align-items: center;
            gap: 16px;
            transition: all 0.3s;
            border: 1px solid transparent;
            animation: slideIn 0.3s ease-out;
        }
        
        @keyframes slideIn {
            from {
                opacity: 0;
                transform: translateX(-20px);
            }
            to {
                opacity: 1;
                transform: translateX(0);
            }
        }
        
        .activity-item:hover {
            border-color: var(--accent);
        }
        
        .activity-icon {
            width: 48px;
            height: 48px;
            border-radius: 8px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-weight: 600;
            font-size: 18px;
        }
        
        .activity-icon.trade {
            background: rgba(14, 203, 129, 0.1);
            color: var(--success);
        }
        
        .activity-icon.order {
            background: rgba(56, 97, 251, 0.1);
            color: var(--info);
        }
        
        .activity-icon.enhanced {
            background: rgba(240, 185, 11, 0.1);
            color: var(--accent);
        }
        
        .activity-details {
            flex: 1;
        }
        
        .activity-main {
            font-weight: 500;
            margin-bottom: 4px;
        }
        
        .activity-sub {
            font-size: 14px;
            color: var(--text-secondary);
        }
        
        .activity-time {
            text-align: right;
        }
        
        .activity-timestamp {
            font-size: 14px;
            color: var(--text-secondary);
        }
        
        .activity-value {
            font-size: 16px;
            font-weight: 600;
            margin-top: 4px;
        }
        
        /* Empty state */
        .empty-state {
            text-align: center;
            padding: 48px;
            color: var(--text-secondary);
        }
        
        /* Error/Success Messages */
        .message {
            padding: 12px;
            border-radius: 8px;
            margin-top: 16px;
            text-align: center;
        }
        
        .message.error {
            background: rgba(246, 70, 93, 0.1);
            border: 1px solid var(--danger);
            color: var(--danger);
        }
        
        .message.success {
            background: rgba(14, 203, 129, 0.1);
            border: 1px solid var(--success);
            color: var(--success);
        }
        
        /* Responsive */
        @media (max-width: 768px) {
            .dashboard {
                padding: 16px;
            }
            
            .grid-cards {
                grid-template-columns: 1fr;
            }
            
            .trading-stats {
                gap: 16px;
            }
        }
    </style>
</head>
<body>
    <div class="header">
        <div class="header-content">
            <div class="logo">
                <span class="enhanced-title">🤖 Enhanced Grid Trading Bot</span>
                <div class="version-badge">V6 ENHANCED</div>
                <div class="trading-status" id="tradingStatus">
                    <div class="status-dot"></div>
                    <span>High-Density Grid Active</span>
                </div>
            </div>
            <div class="balance-display" id="balanceDisplay" style="display: none;">
                <div>
                    <div class="balance-label">Total Balance</div>
                    <div class="balance-value" id="totalBalance">$0.00</div>
                </div>
            </div>
            <div class="controls" id="headerControls" style="display: none;">
                <button class="btn btn-sm btn-toggle" id="toggleBtn" onclick="toggleGridTrading()">
                    Pause Grid
                </button>
                <button class="btn btn-sm" style="background: var(--danger)" onclick="emergencyStop()">
                    🚨 Emergency Stop
                </button>
                <button class="btn btn-sm" onclick="disconnect()">Disconnect</button>
            </div>
        </div>
    </div>
    
    <div class="trading-stats-bar" id="tradingStatsBar" style="display: none;">
        <div class="trading-stats">
            <div class="stat-item">
                <div class="stat-label">Grid Orders</div>
                <div class="stat-value enhanced" id="totalGridOrders">0</div>
            </div>
            <div class="stat-item">
                <div class="stat-label">Grid Trades</div>
                <div class="stat-value" id="gridTrades">0</div>
            </div>
            <div class="stat-item">
                <div class="stat-label">Realized P&L</div>
                <div class="stat-value" id="realizedPnl">$0.00</div>
            </div>
            <div class="stat-item">
                <div class="stat-label">Unrealized P&L</div>
                <div class="stat-value" id="unrealizedPnl">$0.00</div>
            </div>
            <div class="stat-item">
                <div class="stat-label">Total P&L</div>
                <div class="stat-value" id="totalPnl">$0.00</div>
            </div>
            <div class="stat-item">
                <div class="stat-label">Partial Fills</div>
                <div class="stat-value enhanced" id="partialFills">0</div>
            </div>
            <div class="stat-item">
                <div class="stat-label">Win Rate</div>
                <div class="stat-value" id="winRate">0%</div>
            </div>
        </div>
    </div>
    
    <div id="loginContainer" class="login-container">
        <div class="login-card">
            <h2 class="enhanced-title" style="text-align: center; margin-bottom: 8px;">Enhanced Grid Trading Bot V6</h2>
            <p style="text-align: center; color: var(--text-secondary); margin-bottom: 32px;">
                🚀 High-Density Dynamic Grids • 30+ Levels • Geometric Spacing • ATR Analysis
            </p>
            
            <form onsubmit="connect(event)">
                <div class="form-group">
                    <label for="endpoint">Select Endpoint</label>
                    <select id="endpoint" class="form-select">
                        <option value="0">Binance Testnet (Recommended)</option>
                        <option value="1">Binance Main (Paper Trading)</option>
                    </select>
                </div>
                <div class="form-group">
                    <label for="apiKey">API Key</label>
                    <input type="text" id="apiKey" class="form-input" placeholder="Enter your API key" required>
                </div>
                <div class="form-group">
                    <label for="secretKey">Secret Key</label>
                    <input type="password" id="secretKey" class="form-input" placeholder="Enter your secret key" required>
                </div>
                <button type="submit" class="btn" id="connectBtn">Start Enhanced Grid Trading</button>
            </form>
            <div id="loginMessage"></div>
        </div>
    </div>
    
    <div id="dashboard" class="dashboard">
        <!-- Enhanced Grid Overview -->
        <div class="grid-overview">
            <div class="grid-overview-header">
                <div class="grid-overview-title">
                    📊 Enhanced Grid Trading Overview
                    <div class="enhanced-badge">HIGH-DENSITY</div>
                </div>
                <div class="grid-controls">
                    <span style="margin-right: 12px; color: var(--text-secondary);">
                        Grid: <span id="gridLevels" class="enhanced-metric">20-50</span> levels × 
                        <span id="gridRange" class="enhanced-metric">±5-20%</span> • 
                        <span id="gridMode" class="enhanced-metric">Geometric</span>
                    </span>
                </div>
            </div>
            
            <div class="grid-cards" id="gridCards"></div>
        </div>
        
        <!-- Activity Feed -->
        <div class="activity-container">
            <div class="activity-header">
                <div class="activity-title">
                    Live Activity Feed
                    <div class="live-dot"></div>
                    <div class="enhanced-badge">ENHANCED</div>
                </div>
            </div>
            <div class="activity-list" id="activityList">
                <div class="empty-state">Waiting for enhanced trading activity...</div>
            </div>
        </div>
    </div>
    
    <script>
        let updateInterval;
        let currentData = {};
        let gridActive = true;
        
        // Format functions
        function formatNumber(num, decimals = 2) {
            if (num === undefined || num === null) return '0';
            const n = parseFloat(num);
            if (Math.abs(n) < 0.01) return n.toFixed(6);
            if (Math.abs(n) < 1) return n.toFixed(4);
            return n.toFixed(decimals);
        }
        
        function formatTime(timestamp) {
            if (!timestamp) return '-';
            const date = new Date(timestamp);
            const now = new Date();
            const diff = now - date;
            
            if (diff < 60000) return 'Just now';
            if (diff < 3600000) return Math.floor(diff / 60000) + 'm ago';
            if (diff < 86400000) return Math.floor(diff / 3600000) + 'h ago';
            
            return date.toLocaleDateString() + ' ' + date.toLocaleTimeString();
        }
        
        // Connect to Binance
        async function connect(event) {
            event.preventDefault();
            
            const btn = document.getElementById('connectBtn');
            btn.disabled = true;
            btn.textContent = 'Connecting...';
            
            const apiKey = document.getElementById('apiKey').value;
            const secretKey = document.getElementById('secretKey').value;
            const endpoint = document.getElementById('endpoint').value;
            
            try {
                const response = await fetch('/api/connect', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({apiKey, secretKey, endpoint})
                });
                
                const data = await response.json();
                
                if (data.success) {
                    document.getElementById('loginContainer').style.display = 'none';
                    document.getElementById('dashboard').style.display = 'block';
                    document.getElementById('headerControls').style.display = 'flex';
                    document.getElementById('balanceDisplay').style.display = 'block';
                    document.getElementById('tradingStatsBar').style.display = 'block';
                    
                    startMonitoring();
                } else {
                    document.getElementById('loginMessage').innerHTML = 
                        '<div class="message error">Failed to connect. Please check your API credentials.</div>';
                }
            } catch (error) {
                document.getElementById('loginMessage').innerHTML = 
                    '<div class="message error">Connection error: ' + error.message + '</div>';
            }
            
            btn.disabled = false;
            btn.textContent = 'Start Enhanced Grid Trading';
        }
        
        // Start monitoring
        function startMonitoring() {
            loadData();
            updateInterval = setInterval(loadData, 2000);
        }
        
        // Load data
        async function loadData() {
            try {
                const response = await fetch('/api/data');
                const data = await response.json();
                
                currentData = data;
                updateUI(data);
            } catch (error) {
                console.error('Error loading data:', error);
            }
        }
        
        // Update UI
        function updateUI(data) {
            // Update balance
            if (data.account) {
                document.getElementById('totalBalance').textContent = 
                    '$' + formatNumber(data.account.total_balance_usdt);
            }
            
            // Update enhanced trading stats
            updateEnhancedTradingStats(data.stats, data.grid_metrics);
            
            // Update enhanced grid cards
            updateEnhancedGridCards(data.grid_states, data.grid_orders);
            
            // Update activity feed
            updateActivityFeed(data.activities);
            
            // Update enhanced grid config display
            if (data.grid_config) {
                document.getElementById('gridLevels').textContent = data.grid_config.levels || '20-50';
                document.getElementById('gridRange').textContent = '±' + (data.grid_config.range || '5-20%');
                
                // Show grid mode from first active grid
                let gridMode = 'Geometric';
                if (data.grid_states) {
                    const activeGrids = Object.values(data.grid_states).filter(g => g.active);
                    if (activeGrids.length > 0) {
                        gridMode = activeGrids[0].grid_mode || 'geometric';
                        gridMode = gridMode.charAt(0).toUpperCase() + gridMode.slice(1);
                    }
                }
                document.getElementById('gridMode').textContent = gridMode;
            }
        }
        
        // Update enhanced trading stats
        function updateEnhancedTradingStats(stats, metrics) {
            if (!stats) return;
            
            // Count total grid orders
            let totalOrders = 0;
            let totalPartialFills = 0;
            
            if (currentData.grid_orders) {
                Object.values(currentData.grid_orders).forEach(orders => {
                    totalOrders += orders.filter(o => o.status === 'NEW').length;
                });
            }
            
            if (currentData.grid_states) {
                Object.values(currentData.grid_states).forEach(state => {
                    totalPartialFills += state.partial_fills || 0;
                });
            }
            
            document.getElementById('totalGridOrders').textContent = totalOrders;
            document.getElementById('gridTrades').textContent = stats.grid_trades || 0;
            document.getElementById('partialFills').textContent = totalPartialFills;
            
            const realizedEl = document.getElementById('realizedPnl');
            realizedEl.textContent = (stats.realized_pnl >= 0 ? '+' : '') + ' + formatNumber(stats.realized_pnl);
            realizedEl.className = 'stat-value ' + (stats.realized_pnl >= 0 ? 'positive' : 'negative');
            
            const unrealizedEl = document.getElementById('unrealizedPnl');
            unrealizedEl.textContent = (stats.unrealized_pnl >= 0 ? '+' : '') + ' + formatNumber(stats.unrealized_pnl);
            unrealizedEl.className = 'stat-value ' + (stats.unrealized_pnl >= 0 ? 'positive' : 'negative');
            
            const totalEl = document.getElementById('totalPnl');
            totalEl.textContent = (stats.total_pnl >= 0 ? '+' : '') + ' + formatNumber(stats.total_pnl);
            totalEl.className = 'stat-value ' + (stats.total_pnl >= 0 ? 'positive' : 'negative');
            
            document.getElementById('winRate').textContent = formatNumber(stats.win_rate) + '%';
        }
        
        // Update enhanced grid cards
        function updateEnhancedGridCards(gridStates, gridOrders) {
            const container = document.getElementById('gridCards');
            const symbols = currentData.selected_cryptos || ['BTCUSDT', 'ETHUSDT', 'BNBUSDT', 'SOLUSDT', 'ADAUSDT'];
            
            container.innerHTML = symbols.map(symbol => {
                const state = gridStates && gridStates[symbol] ? gridStates[symbol] : {
                    active: false,
                    current_price: 0,
                    grid_center: 0,
                    buy_orders: 0,
                    sell_orders: 0,
                    volatility: 0,
                    grid_levels: 30,
                    grid_mode: 'geometric',
                    atr_pct: 0,
                    liquidity_score: 1.0,
                    rebalance_threshold: 2.0
                };
                
                const orders = gridOrders && gridOrders[symbol] ? gridOrders[symbol] : [];
                const activeOrders = orders.filter(o => o.status === 'NEW');
                
                return `
                    <div class="grid-card ${state.active ? 'active' : ''}">
                        <div class="grid-header">
                            <div class="grid-symbol">${symbol}</div>
                            <div class="grid-status ${state.active ? '' : 'inactive'}">
                                ${state.active ? 'ENHANCED' : 'INACTIVE'}
                            </div>
                        </div>
                        <div class="grid-info">
                            <div class="grid-info-row">
                                <span class="grid-info-label">Current Price</span>
                                <span style="font-weight: 600;">${formatNumber(state.current_price)}</span>
                            </div>
                            <div class="grid-info-row">
                                <span class="grid-info-label">Grid Center</span>
                                <span>${formatNumber(state.grid_center)}</span>
                            </div>
                            <div class="grid-info-row">
                                <span class="grid-info-label">Grid Levels</span>
                                <span class="enhanced-metric">${state.grid_levels || 30}</span>
                            </div>
                            <div class="grid-info-row">
                                <span class="grid-info-label">Grid Mode</span>
                                <span class="enhanced-metric">${(state.grid_mode || 'geometric').toUpperCase()}</span>
                            </div>
                            <div class="grid-info-row">
                                <span class="grid-info-label">ATR %</span>
                                <span class="enhanced-metric">${formatNumber(state.atr_pct || 0, 2)}%</span>
                            </div>
                            <div class="grid-info-row">
                                <span class="grid-info-label">Volatility</span>
                                <span>${formatNumber(state.volatility || 0, 2)}%</span>
                            </div>
                            <div class="grid-info-row">
                                <span class="grid-info-label">Liquidity Score</span>
                                <span class="enhanced-metric">${formatNumber(state.liquidity_score || 1.0, 2)}</span>
                            </div>
                            <div class="grid-info-row">
                                <span class="grid-info-label">Rebalance @</span>
                                <span>${formatNumber(state.rebalance_threshold || 2.0, 1)}%</span>
                            </div>
                        </div>
                        <div class="grid-orders-summary">
                            <div class="order-count">
                                <span class="order-count-value" style="color: var(--success)">
                                    ${state.buy_orders || 0}
                                </span>
                                <span class="order-count-label">Buy Orders</span>
                            </div>
                            <div class="order-count">
                                <span class="order-count-value" style="color: var(--danger)">
                                    ${state.sell_orders || 0}
                                </span>
                                <span class="order-count-label">Sell Orders</span>
                            </div>
                            <div class="order-count">
                                <span class="order-count-value" style="color: var(--accent)">
                                    ${activeOrders.length}
                                </span>
                                <span class="order-count-label">Total Active</span>
                            </div>
                            <div class="order-count">
                                <span class="order-count-value" style="color: var(--info)">
                                    ${state.partial_fills || 0}
                                </span>
                                <span class="order-count-label">Partial Fills</span>
                            </div>
                        </div>
                    </div>
                `;
            }).join('');
        }
        
        // Update activity feed
        function updateActivityFeed(activities) {
            const container = document.getElementById('activityList');
            
            if (!activities || activities.length === 0) {
                container.innerHTML = '<div class="empty-state">Waiting for enhanced trading activity...</div>';
                return;
            }
            
            container.innerHTML = activities.slice(-50).reverse().map(activity => {
                let icon, iconClass, mainText, subText, value;
                
                if (activity.type === 'grid_order') {
                    icon = 'G';
                    iconClass = 'enhanced';
                    mainText = `Enhanced Grid ${activity.side} Order - ${activity.symbol}`;
                    subText = `Level ${activity.grid_level || ''} • ${formatNumber(activity.quantity)} @ ${formatNumber(activity.price)}`;
                    value = ' + formatNumber(activity.price * activity.quantity);
                } else if (activity.type === 'grid_filled') {
                    icon = '✓';
                    iconClass = 'trade';
                    mainText = `Grid Order FILLED - ${activity.symbol}`;
                    subText = `Level ${activity.grid_level || ''} • ${activity.side} ${formatNumber(activity.quantity)} @ ${formatNumber(activity.price)}`;
                    value = ' + formatNumber(activity.price * activity.quantity);
                } else if (activity.type === 'trade') {
                    icon = 'T';
                    iconClass = 'trade';
                    mainText = `${activity.side} Trade Executed - ${activity.symbol}`;
                    subText = `${formatNumber(activity.quantity)} @ ${formatNumber(activity.price)}`;
                    value = ' + formatNumber(activity.price * activity.quantity);
                } else {
                    icon = '?';
                    iconClass = 'order';
                    mainText = activity.type;
                    subText = JSON.stringify(activity);
                    value = '';
                }
                
                return `
                    <div class="activity-item">
                        <div class="activity-icon ${iconClass}">${icon}</div>
                        <div class="activity-details">
                            <div class="activity-main">${mainText}</div>
                            <div class="activity-sub">${subText}</div>
                        </div>
                        <div class="activity-time">
                            <div class="activity-timestamp">${formatTime(activity.time)}</div>
                            <div class="activity-value">${value}</div>
                        </div>
                    </div>
                `;
            }).join('');
        }
        
        // Toggle grid trading
        async function toggleGridTrading() {
            gridActive = !gridActive;
            
            const btn = document.getElementById('toggleBtn');
            const status = document.getElementById('tradingStatus');
            
            btn.textContent = gridActive ? 'Pause Grid' : 'Resume Grid';
            btn.classList.toggle('inactive', !gridActive);
            status.classList.toggle('inactive', !gridActive);
            status.querySelector('span').textContent = gridActive ? 'High-Density Grid Active' : 'Grid Trading Paused';
            
            try {
                await fetch('/api/toggle_grid', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({active: gridActive})
                });
            } catch (error) {
                console.error('Toggle error:', error);
            }
        }
        
        // Emergency stop
        async function emergencyStop() {
            if (!confirm('Are you sure you want to emergency stop all enhanced trading?')) return;
            
            try {
                await fetch('/api/emergency_stop', {method: 'POST'});
                alert('Emergency stop executed! All enhanced orders canceled.');
                disconnect();
            } catch (error) {
                alert('Emergency stop failed: ' + error.message);
            }
        }
        
        // Disconnect
        function disconnect() {
            if (updateInterval) clearInterval(updateInterval);
            location.reload();
        }
        
        // Cleanup
        window.addEventListener('beforeunload', () => {
            if (updateInterval) clearInterval(updateInterval);
        });
    </script>
</body>
</html>
'''

# ============================================================================
# MAIN FUNCTION
# ============================================================================

def main() -> None:
    """Main entry point with enhanced startup information."""
    load_state()
    
    print("\n" + "="*80)
    print("🤖 ENHANCED Binance Grid Trading Bot V6 - HIGH-DENSITY DYNAMIC GRIDS")
    print("="*80)
    print("🌐 URL: http://localhost:8080")
    print("\n🚀 MAJOR ENHANCEMENTS - PROFESSIONAL CLEAN CODE:")
    print("\n📊 HIGH-DENSITY GRID SYSTEM:")
    print("   • Base Grid Levels: 30 (up from 5) - 6X MORE ORDERS!")
    print("   • Dynamic Range: 20-50 levels based on volatility")
    print("   • Minimum 20 levels even in high volatility")
    print("   • Maximum 50 levels in low volatility markets")
    
    print("\n⚡ ENHANCED VOLATILITY ANALYSIS:")
    print("   • ATR (Average True Range) calculations")
    print("   • Multi-timeframe analysis (1h, 15m, 1m)")
    print("   • Dynamic rebalance thresholds (1.5-4%)")
    print("   • Real-time volatility adaptation")
    
    print("\n🎯 GEOMETRIC GRID SPACING:")
    print("   • Percentage-based intervals (vs linear)")
    print("   • Better price distribution")
    print("   • Optimal for crypto price movements")
    print("   • Fallback to linear mode available")
    
    print("\n🔄 PARTIAL FILL HANDLING:")
    print("   • Detects 30%+ filled orders")
    print("   • Places immediate replacement orders")
    print("   • Maximizes capital efficiency")
    print("   • Tracks partial fill metrics")
    
    print("\n📈 MARKET MICROSTRUCTURE AWARENESS:")
    print("   • Order book depth analysis")
    print("   • Liquidity score calculations")
    print("   • Price adjustment for thin areas")
    print("   • Smart order placement")
    
    print("\n🎛️ DYNAMIC ORDER SIZING:")
    print("   • Base: 0.5% per order (down from 2%)")
    print("   • Scales with volatility and grid count")
    print("   • More orders = smaller individual sizes")
    print("   • Better risk distribution")
    
    print("\n🔧 YOUR SELECTED CRYPTOCURRENCIES:")
    for i, symbol in enumerate(GRID_CONFIG['symbols'], 1):
        asset = symbol.replace('USDT', '')
        names = {
            'BTC': 'Bitcoin', 'ETH': 'Ethereum', 'BNB': 'Binance Coin',
            'SOL': 'Solana', 'ADA': 'Cardano'
        }
        print(f"   • {symbol} - {names.get(asset, asset)}")
    
    print("\n⚙️ ENHANCED GRID CONFIGURATION:")
    print(f"   • Base Grid Levels: {GRID_CONFIG['base_grid_levels']} (was 5)")
    print(f"   • Range: {GRID_CONFIG['min_grid_levels']}-{GRID_CONFIG['max_grid_levels']} levels")
    print(f"   • Grid Range: {GRID_CONFIG['base_grid_range']}-{GRID_CONFIG['max_grid_range']}% (was 2%)")
    print(f"   • Grid Mode: {GRID_CONFIG['grid_mode'].title()}")
    print(f"   • Order Size: {GRID_CONFIG['base_order_size_percent']*100}% (was 2%)")
    
    print("\n📊 ENHANCED VOLATILITY STRATEGY:")
    print("   • High volatility (>3% ATR): 20-25 levels, wider range")
    print("   • Normal volatility (1-3% ATR): 30 levels, 5-10% range")
    print("   • Low volatility (<1% ATR): 40-50 levels, tight range")
    
    print("\n✅ ENHANCED FEATURES:")
    print("   • 🔥 6X MORE GRID ORDERS")
    print("   • 📊 ATR-based volatility analysis")
    print("   • 🎯 Geometric price distribution")
    print("   • ⚡ Partial fill optimization")
    print("   • 📈 Liquidity-aware placement")
    print("   • 🔄 Dynamic rebalancing")
    print("   • 📊 Enhanced performance metrics")
    print("   • 🎛️ Smart capital allocation")
    
    print("\n📊 PERFORMANCE TRACKING:")
    print("   • Grid efficiency metrics")
    print("   • ATR calculation count")
    print("   • Partial fills handled")
    print("   • Liquidity adjustments")
    print("   • Geometric grid usage")
    print("   • Enhanced order placement stats")
    
    print("\n🔧 CODE QUALITY IMPROVEMENTS:")
    print("   • Professional clean architecture")
    print("   • Enhanced error handling")
    print("   • Comprehensive type hints")
    print("   • Thread-safe operations")
    print("   • Modular design patterns")
    print("   • Extensive documentation")
    
    print("\n📌 Press Ctrl+C to stop gracefully")
    print("="*80 + "\n")
    
    # Create and start HTTP server
    try:
        server = HTTPServer(('localhost', 8080), HTTPRequestHandler)
        
        # Attempt to open browser
        try:
            import webbrowser
            webbrowser.open('http://localhost:8080')
        except ImportError:
            pass
        
        logger.info("🌐 Server started at http://localhost:8080")
        server.serve_forever()
        
    except KeyboardInterrupt:
        print("\n✅ Enhanced server stopped gracefully")
        if 'server' in locals():
            server.shutdown()
    except Exception as e:
        logger.error(f"Server error: {e}")
    finally:
        cleanup()


if __name__ == '__main__':
    main()