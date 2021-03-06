""" Takes text data and parses it for specified pattern to generate order parameters """
import logging
import re


def text_to_order_params(string: str):
    """ Parses string for signal. If string contains one and only one order signal,
    then it returns the order parameters as strings and any additional comments,
    else returns None
    Format example:
        'STC INTC 50C 12/31 @.45'
        <Open/close> <ticker> <strike price + call or put> <expiration date> <@ price>
    """
    # Regex Formatting
    # () denote regex groupings. Regex 'or' uses short-circuit evaluation
    # (?<!\S) is negative lookbehind assertion for any non-whitespace character
    # BTO/STC cannot be preceded by any non-whitespace character
    instruction = "((?<!\S)BTO|(?<!\S)STC)"
    ticker_pattern = "([A-Z]{1,5})"  # 1-5 capitalized letters

    # 1-5 numbers with optional two decimals
    strike_price = "([0-9]{1,5}\.[0-9]{1,2}|[0-9]{1,5})"
    contract_type = "([CP]{1})"  # either C or P

    # can be month/day/year(2 or 4 digit year) or month/day
    # month and day can be 1-2 digits
    # regex tries to match patterns from left to right with or ( | ) operator
    expiration_date = "([0-9]{1,2}/[0-9]{1,2}/[0-9]{4}|[0-9]{1,2}/[0-9]{1,2}/[0-9]{2}|[0-9]{1,2}/[0-9]{1,2})"

    # (?!\S) is negative lookahead assertion for any non-whitespace
    # (?=[(]) is positive lookahead assertion for open parentheses
    # contract price is up to 3 digit number followed by 1-2 decimals
    # and either no non-whitespace or an open parentheses
    contract_price = "([0-9]{0,3}\.[0-9]{1,2}((?!\S)|(?=[(])))"
    space = "\s{1,2}"  # 1-2 spaces
    at = "@\s{0,1}"  # @ followed by 0-1 spaces
    regex_pattern = (
        instruction
        + space
        + ticker_pattern
        + space
        + strike_price
        + contract_type
        + space
        + expiration_date
        + space
        + at
        + contract_price
    )

    # Outputs
    order_params = {
        "instruction": None,
        "ticker": None,
        "strike_price": None,
        "contract_type": None,
        "expiration": None,
        "contract_price": None,
        "comments": None,
        "flags": {"SL": None, "risk_level": None, "reduce": None},
    }

    # strip markdown from text
    clean_string = strip_markdown(string)

    # Text should contain one and only one order signal
    matches = [match for match in re.finditer(regex_pattern, clean_string)]
    if len(matches) == 1:
        match = matches[0]  # match is re.Match object
        match.groups()
        order_params["instruction"] = match.group(1)
        order_params["ticker"] = match.group(2)
        order_params["strike_price"] = match.group(3)
        order_params["contract_type"] = match.group(4)
        order_params["expiration"] = match.group(5)
        order_params["contract_price"] = match.group(6)
        start, end = match.span()
        comments = clean_string[end:]
        if comments != "":
            order_params["comments"] = comments
            if order_params["instruction"] == "BTO":
                order_params["flags"]["SL"] = parse_sl(order_params["comments"])
                order_params["flags"]["risk_level"] = parse_risk(
                    order_params["comments"]
                )
            elif order_params["instruction"] == "STC":
                order_params["flags"]["reduce"] = parse_reduce(order_params["comments"])
    elif len(matches) > 1:
        logging.warning("Two or matches detected in string")

    if order_params == {
        "instruction": None,
        "ticker": None,
        "strike_price": None,
        "contract_type": None,
        "expiration": None,
        "contract_price": None,
        "comments": None,
        "flags": {"SL": None, "risk_level": None, "reduce": None},
    }:
        return None
    else:
        return order_params


def parse_sl(comments: str):
    """Parses comments for SL on an order"""
    parsed = None
    sl_at = "(SL\s{0,1}@\s{0,1})"
    sl_price = "([0-9]{0,3}\.[0-9]{1,2}((?!\S)|(?=[)])))"
    pattern = sl_at + sl_price
    match = re.search(pattern, comments)
    if match:
        match.groups()
        parsed = match.group(2)
    return parsed


def parse_risk(comments: str):
    """Parses tests for key terms indicating high risk. Returns "high risk" if terms are
    found, else returns None. Key terms must not have alphanumeric character before or
    after term"""
    parsed = None
    pattern = "(?<!\w)((risky)|(daytrade)|(small\sposition)|(light\sposition))(?!\w)"
    match = re.search(pattern, comments, flags=re.IGNORECASE)
    if match:
        parsed = "high risk"
    return parsed


def parse_reduce(comments: str):
    """Parses text for signal to reduce position by XX%.
    Returns XX% as a string if found, else returns None"""
    parsed = None
    pattern = "(?<!\w)(closing|trim)(\s)([0-9]{1,3}%)(?!\w)"
    match = re.search(pattern, comments, flags=re.IGNORECASE)
    if match:
        parsed = match.group(3)
    return parsed


def strip_markdown(string: str):
    """Removes underscores and asterisks"""
    clean_str = string.replace("*", "")
    clean_str = clean_str.replace("_", "")
    return clean_str
