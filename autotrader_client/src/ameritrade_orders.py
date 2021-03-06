"""Functions needed to execute TD Ameritrade orders"""

import sys
import tda
import tda.orders.options
import json
import logging
import datetime
import math
import src.validate_params as vp
from src.client_settings import (
    TD_TOKEN_PATH,
    TD_AUTH_PARAMS_PATH,
    TD_DICT_KEY_API,
    TD_DICT_KEY_URI,
    TD_DICT_KEY_ACCT,
    ORD_SETTINGS_PATH,
    MAX_ORD_VAL_KEY,
    RISKY_ORD_VAL_KEY,
    BUY_LIM_KEY,
    SL_KEY,
)


def initialize_order(ord_params):
    """Initialize TDA and order related values,
    authenticate with TDA site and place order"""

    # initialize values
    td_acct = {}
    with open(TD_AUTH_PARAMS_PATH) as fp:
        td_auth_params = json.load(fp)
    td_acct["uri"] = td_auth_params[TD_DICT_KEY_URI]
    td_acct["api_key"] = td_auth_params[TD_DICT_KEY_API]
    td_acct["acct_num"] = td_auth_params[TD_DICT_KEY_ACCT]

    with open(ORD_SETTINGS_PATH) as fp:
        order_settings = json.load(fp)
    # max_ord_val is max $ value of order e.g. 500.00
    # high_risk_ord_value is the order value for higher risk orders
    usr_set = {
        "max_ord_val": order_settings[MAX_ORD_VAL_KEY],
        "high_risk_ord_val": order_settings[RISKY_ORD_VAL_KEY],
        "buy_limit_percent": order_settings[BUY_LIM_KEY],
        "SL_percent": order_settings[SL_KEY],
    }

    # check user inputs
    vp.validate_user_settings(usr_set)

    # authenticate
    client = authenticate_tda_account(TD_TOKEN_PATH, td_acct["api_key"], td_acct["uri"])

    # generate and place order
    if ord_params["instruction"] == "BTO":
        process_bto_order(client, td_acct["acct_num"], ord_params, usr_set)
    elif ord_params["instruction"] == "STC":
        process_stc_order(client, td_acct["acct_num"], ord_params, usr_set)
    else:
        instr = ord_params["instruction"]
        logging.warning(f"Invalid order instruction: {instr}")


# creating more than one client will likely cause issues with authentication
def authenticate_tda_account(token_path: str, api_key: str, redirect_uri: str):
    """Takes path to locally stored auth token, TDA app key, and redirect uri then tries
    to authenticate. If unable to authenticate with token, performs backup
    authentication from login auth flow. Returns authenticated client_tests object"""
    client = None
    try:
        # tda.auth automatically creates and updates token file at token_path
        client = tda.auth.client_from_token_file(token_path, api_key)
    except FileNotFoundError:
        # should on first log-in before token has been retrieved and saved by tda.auth
        from src.client_settings import GECKODRIVER_PATH
        from selenium import webdriver

        # Note that the webdriver executable for your OS must be downloaded and
        # saved at the set path. Other webdrivers like Chrome can also be used
        with webdriver.Firefox(executable_path=GECKODRIVER_PATH) as driver:
            client = tda.auth.client_from_login_flow(
                driver, api_key, redirect_uri, token_path
            )
    return client


def build_option_symbol(ord_params: dict):
    """ Returns option symbol as string from order parameters dictionary.
    Note that expiration_date must be datetime.datetime object"""
    symbol_builder_class = tda.orders.options.OptionSymbol(
        underlying_symbol=ord_params["ticker"],
        expiration_date=ord_params["expiration"],  # datetime.datetime obj
        contract_type=ord_params["contract_type"],
        strike_price_as_string=ord_params["strike_price"],
    )
    # OptionSymbol class does not return symbol until build method is called
    symbol = symbol_builder_class.build()
    return symbol


def output_response(ord_params: dict, response):
    """Logs non-json response and sends it to std.out"""
    logging.info(ord_params)
    logging.info(response)
    print(ord_params)
    print(f"Processed order. Response received: {response}")


# BTO-related functions
def process_bto_order(client, acct_num: str, ord_params: dict, usr_set: dict):
    """Prepare and place BTO order"""
    # determine risk level and corresponding order size
    if ord_params["flags"]["risk_level"] == "high risk":
        order_value = usr_set["high_risk_ord_val"]
    else:
        order_value = usr_set["max_ord_val"]
    # determine purchase quantity
    buy_qty = calc_buy_order_quantity(
        ord_params["contract_price"], order_value, usr_set["buy_limit_percent"],
    )
    if buy_qty >= 1:
        option_symbol = build_option_symbol(ord_params)

        # Use more conservative SL if there are two
        sl_percent = usr_set["SL_percent"]
        if ord_params["flags"]["SL"] is not None:
            rec_sl = float(ord_params["flags"]["SL"])
            rec_sl_percent = calc_sl_percentage(ord_params["contract_price"], rec_sl)
            if rec_sl_percent < usr_set["SL_percent"]:
                sl_percent = rec_sl_percent
        sl_price = calc_sl_price(ord_params["contract_price"], sl_percent)
        buy_lim_price = calc_buy_limit_price(
            ord_params["contract_price"], usr_set["buy_limit_percent"]
        )

        # prepare buy limit order and accompanying stop loss order
        ota_order = build_bto_order_w_stop_loss(
            option_symbol, buy_qty, buy_lim_price, sl_price
        )
        response = client.place_order(acct_num, order_spec=ota_order)
        output_response(ord_params, response)

    else:
        msg1 = f"{ord_params} purchase quantity is 0\n"
        msg2 = "This may be due to a low max order value or high buy limit percent\n\n"
        sys.stderr.write(msg1 + msg2)


def calc_buy_order_quantity(price: float, ord_val: float, limit_percent: float):
    """Returns the order quantity (int) for a buy order based on
    the option price, maximum order size, and buy limit percent  """
    lot_size = 100  # standard lot size value
    lot_value = price * lot_size * (1 + limit_percent)
    quantity = ord_val / lot_value
    return int(quantity)  # int() rounds down


def calc_buy_limit_price(contract_price, buy_limit_percent):
    """Returns buy limit price that is buy_limit_percent above the contract price"""
    return round(contract_price * (1 + buy_limit_percent), 2)


def calc_sl_percentage(contract_price: float, sl_price: float):
    """Returns percentage difference from contract price to stop loss price. """
    return (contract_price - sl_price) / contract_price


def calc_sl_price(contract_price, sl_percent):
    """Returns price that is sl_percent below the contract price"""
    return round(contract_price * (1 - sl_percent), 2)


def build_bto_order_w_stop_loss(
    option_symbol: str, qty: int, buy_lim_price: float, sl_price: float, kill_fill=True,
):
    """Prepares and returns OrderBuilder object for one-trigger another order.
    First order is BTO limit and second order is STC stop-market"""

    # prepare pre-filled OrderBuilder objs
    bto_lim = tda.orders.options.option_buy_to_open_limit(
        option_symbol, qty, buy_lim_price
    )
    if kill_fill is True:
        bto_lim.set_duration(tda.orders.common.Duration.FILL_OR_KILL)
    stc_stop_market = build_stc_stop_market_order(option_symbol, qty, sl_price)
    one_trigger_other = tda.orders.common.first_triggers_second(
        bto_lim, stc_stop_market
    )
    return one_trigger_other


# STC-related function
def process_stc_order(client, acct_num: str, ord_params: dict, usr_set: dict):
    """ Prepare and place STC order"""
    option_symbol = build_option_symbol(ord_params)
    pos_qty = get_position_quant(client, acct_num, option_symbol)
    if pos_qty is not None and pos_qty >= 1:
        # cancel existing STC orders (like stop-markets)
        existing_stc_ids = get_existing_stc_orders(client, option_symbol)
        if len(existing_stc_ids) > 0:
            for ord_id in existing_stc_ids:
                response = client.cancel_order(ord_id, acct_num)
                logging.info(response.content)

        # if the STC order is meant to reduce the position, sell the suggested %
        # then issue a new STC stop-market for the remainder
        if ord_params["flags"]["reduce"] is not None:
            sell_qty, keep_qty = calc_position_reduction(
                pos_qty, ord_params["flags"]["reduce"]
            )

            stc = build_stc_market_order(option_symbol, sell_qty)
            response_stc = client.place_order(acct_num, order_spec=stc)

            new_sl_price = calc_sl_price(
                ord_params["contract_price"], usr_set["SL_percent"]
            )
            output_response(ord_params, response_stc)

            if keep_qty > 0:
                stc_stop = build_stc_stop_market_order(
                    option_symbol, keep_qty, new_sl_price
                )
                response_stop = client.place_order(acct_num, order_spec=stc_stop)
                output_response(ord_params, response_stop)

        # else sell the entire position
        else:
            stc = build_stc_market_order(option_symbol, pos_qty)
            response = client.place_order(acct_num, order_spec=stc)
            output_response(ord_params, response)


def get_position_quant(client, acct_id: str, symbol: str):
    """Takes client, account_id, and symbol to search for.
    Returns position long quantity for symbol"""
    response = client.get_account(
        acct_id, fields=tda.client.Client.Account.Fields.POSITIONS
    )
    summary = response.json()
    positions = summary["securitiesAccount"]["positions"]
    for position in positions:
        if position["instrument"]["symbol"] == symbol:
            return float(position["longQuantity"])


def get_existing_stc_orders(client, symbol: str, hours=32):
    """Returns a list of existing single-leg STC orders for the given symbol.
    This library is not currently designed to work with multi-leg (complex) orders"""
    now = datetime.datetime.utcnow()
    query_start = now - datetime.timedelta(hours=hours)
    statuses = (
        tda.client.Client.Order.Status.FILLED,
        tda.client.Client.Order.Status.QUEUED,
        tda.client.Client.Order.Status.ACCEPTED,
        tda.client.Client.Order.Status.WORKING,
    )  # waiting for tda patch to implement multi-status check and speed up query time

    response = client.get_orders_by_query(
        from_entered_datetime=query_start, statuses=None
    )
    summary = response.json()
    order_ids = []
    for order in summary:
        # is the order an in-effect STC order?
        stc_found = check_stc_order(order, symbol)
        if stc_found is not None:
            order_ids.append(stc_found)

        # does the order have a child order that is an in-effect STC order?
        elif order["orderStrategyType"] == "TRIGGER":  # has a child order
            # not currently handling conditional orders with more than one child order
            child = order["childOrderStrategies"][0]
            child_order_stc = check_stc_order(child, symbol)
            if child_order_stc is not None:
                order_ids.append(child_order_stc)
    return order_ids


def check_stc_order(order, symbol):
    """Return order id if order has an in-effect STC order
    for input symbol, else return None"""
    if order["status"] in ["WORKING", "QUEUED", "ACCEPTED"]:
        if len(order["orderLegCollection"]) == 1:  # no multi-leg orders
            instruct = order["orderLegCollection"][0]["instruction"]
            ord_symbol = order["orderLegCollection"][0]["instrument"]["symbol"]
            if ord_symbol == symbol and instruct == "SELL_TO_CLOSE":
                return str(order["orderId"])


def calc_position_reduction(pos_qty: int, percent: float):
    """Calculate the quantity that should be immediately sold and the quantity that
    should be held with an STC stop market in place. Returns sell / keep quantities"""
    sell_qty = math.ceil(pos_qty * percent)
    keep_qty = pos_qty - sell_qty
    return sell_qty, keep_qty


def build_stc_market_order(symbol: str, pos_qty: float):
    """ Returns STC market order OrderBuilder obj"""
    return tda.orders.options.option_sell_to_close_market(symbol, pos_qty)


def build_stc_stop_market_order(symbol: str, qty: int, stop_price: float):
    """Return an OrderBuilder object for a STC stop-market order"""
    order = tda.orders.options.option_sell_to_close_market(symbol, qty)
    order.set_duration(tda.orders.common.Duration.GOOD_TILL_CANCEL)
    order.set_order_type(tda.orders.common.OrderType.STOP)
    trunc_price = round(stop_price, 2)
    order.set_stop_price(trunc_price)  # truncated float
    return order
