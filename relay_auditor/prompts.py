"""Never fall back to echoed terminal input for private values."""
import getpass
import warnings

def hidden(prompt):
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error',getpass.GetPassWarning)
            return getpass.getpass(prompt)
    except getpass.GetPassWarning:
        raise ValueError('interactive_terminal_required') from None
