#!/usr/bin/env python

import hashlib
import base64
import hmac
import os
import datetime
import requests
import xmltodict
import logging
from logging.handlers import SMTPHandler
from dotenv import load_dotenv
from raven.contrib.flask import Sentry
from xml.etree.ElementTree import Element, SubElement, tostring

from flask import Flask, request
app = Flask(__name__)

# remember - to run locally:
# export FLASK_APP=app.py FLASK_DEBUG=1

SHOPIFY_API_SECRET = os.environ.get('SHOPIFY_API_SECRET', '')
MDS_WS_ENDPOINT = os.environ.get('MDS_WS_ENDPOINT', '')
MDS_CLIENT_CODE = os.environ.get('MDS_CLIENT_CODE', '')
MDS_CLIENT_SIGNATURE = os.environ.get('MDS_CLIENT_SIGNATURE', '')
MDS_TEST = os.environ.get('MDS_TEST', 'Y')
SENTRY_DSN = os.environ.get('SENTRY_DSN', '')

SENDGRID_HOST = 'smtp.sendgrid.net'
SENDGRID_PORT = 587
SENDGRID_USERNAME = os.environ.get('SENDGRID_USERNAME', '')
SENDGRID_PASSWORD = os.environ.get('SENDGRID_PASSWORD', '')

# if running in debug mode (i.e. locally) get from .env
if app.debug:
    dotenv_path = os.path.join(os.path.dirname(__file__), '.env')
    load_dotenv(dotenv_path)

sentry = Sentry(app, dsn=SENTRY_DSN)

ADMINS = ['kevin@activefrequency.com']
if not app.debug:
    mail_handler = SMTPHandler(mailhost=(SENDGRID_HOST, SENDGRID_PORT), fromaddr='kevin@activefrequency.com', toaddrs=ADMINS,
        subject="Tranquilo: Shopify-MDS Error", credentials=(SENDGRID_USERNAME, SENDGRID_PASSWORD), secure=())
    mail_handler.setLevel(logging.ERROR)
    app.logger.addHandler(mail_handler)


# Helper to validate hmac
def _hmac_is_valid(secret, body, hmac_to_verify):
    hmac_hash = hmac.new(secret, body, hashlib.sha256)
    hmac_calculated = base64.b64encode(hmac_hash.digest())
    return hmac_calculated == hmac_to_verify


@app.route('/webhook', methods=['POST'])
def webhook():
    # validate the request
    try:
        webhook_hmac = request.headers['X-Shopify-Hmac-Sha256']
        data = request.get_json()
    except:
        app.logger.error("Error receiving webhook")
        return 'Bad Request (missing data)', 400

    # Verify the HMAC
    if not _hmac_is_valid(SHOPIFY_API_SECRET, request.data, webhook_hmac):
        app.logger.error("Error validating webhook")
        return 'Bad Request (failed validation)', 400

    app.logger.debug("Got Shopify webhook")

    # got the webhook from Shopify - now construct the request to MDS
    root = Element('MDSOrder')
    root.set('xml:lang', 'en-US')

    client_code = SubElement(root, 'ClientCode')
    client_code.text = MDS_CLIENT_CODE

    client_signature = SubElement(root, 'ClientSignature')
    client_signature.text = MDS_CLIENT_SIGNATURE

    Order = SubElement(root, 'Order')

    Test = SubElement(Order, 'Test')
    Test.text = MDS_TEST
    OrderID = SubElement(Order, 'OrderID')
    OrderID.text = str(data['order_number'])
    OrderDate = SubElement(Order, 'OrderDate')
    OrderDate.text = datetime.datetime.strptime(data['created_at'][0:10], '%Y-%m-%d').strftime('%m/%d/%Y')

    ShipCompany = SubElement(Order, 'ShipCompany')
    ShipCompany.text = data['shipping_address']['company']
    Shipname = SubElement(Order, 'Shipname')
    Shipname.text = data['shipping_address']['name']
    ShipAddress1 = SubElement(Order, 'ShipAddress1')
    ShipAddress1.text = data['shipping_address']['address1']
    ShipAddress2 = SubElement(Order, 'ShipAddress2')
    ShipAddress2.text = data['shipping_address']['address2']
    ShipCity = SubElement(Order, 'ShipCity')
    ShipCity.text = data['shipping_address']['city']
    ShipState = SubElement(Order, 'ShipState')
    ShipState.text = data['shipping_address']['province_code']
    ShipCountry = SubElement(Order, 'ShipCountry')
    ShipCountry.text = data['shipping_address']['country_code']
    ShipZip = SubElement(Order, 'ShipZip')
    ShipZip.text = data['shipping_address']['zip']
    ShipPhone = SubElement(Order, 'ShipPhone')
    ShipPhone.text = data['shipping_address']['phone']
    ShipEmail = SubElement(Order, 'ShipEmail')
    ShipEmail.text = data['contact_email']

    BillCompany = SubElement(Order, 'BillCompany')
    BillCompany.text = data['billing_address']['company']
    Billname = SubElement(Order, 'Billname')
    Billname.text = data['billing_address']['name']
    BillAddress1 = SubElement(Order, 'BillAddress1')
    BillAddress1.text = data['billing_address']['address1']
    BillAddress2 = SubElement(Order, 'BillAddress2')
    BillAddress2.text = data['billing_address']['address2']
    BillCity = SubElement(Order, 'BillCity')
    BillCity.text = data['billing_address']['city']
    BillState = SubElement(Order, 'BillState')
    BillState.text = data['billing_address']['province_code']
    BillCountry = SubElement(Order, 'BillCountry')
    BillCountry.text = data['billing_address']['country_code']
    BillZip = SubElement(Order, 'BillZip')
    BillZip.text = data['billing_address']['zip']

    OrderTotal = SubElement(Order, 'OrderTotal')
    OrderTotal.text = data['total_price']
    OrderNotes = SubElement(Order, 'OrderNotes')
    OrderNotes.text = data['note']

    Lines = SubElement(Order, "Lines")
    line_item_num = 0
    for line in data['line_items']:
        line_item_num += 1
        Line = SubElement(Lines, "Line", {'number': str(line_item_num).zfill(3)})

        CUSTItemID = SubElement(Line, 'CUSTItemID')
        CUSTItemID.text = line['sku']
        RetailerItemID = SubElement(Line, 'RetailerItemID')
        RetailerItemID.text = line['sku']
        Description = SubElement(Line, 'Description')
        Description.text = line['title']
        PricePerUnit = SubElement(Line, 'PricePerUnit')
        PricePerUnit.text = line['price']
        Qty = SubElement(Line, 'Qty')
        Qty.text = str(line['quantity'])

    xml_string = tostring(root, method='xml', encoding='UTF-8')

    # These two lines enable debugging at httplib level (requests->urllib3->http.client)
    # You will see the REQUEST, including HEADERS and DATA, and RESPONSE with HEADERS but without DATA.
    # The only thing missing will be the response.body which is not logged.
    # import httplib as http_client
    # http_client.HTTPConnection.debuglevel = 1

    # # You must initialize logging, otherwise you'll not see debug output.
    # logging.basicConfig()
    # logging.getLogger().setLevel(logging.DEBUG)
    # requests_log = logging.getLogger("requests.packages.urllib3")
    # requests_log.setLevel(logging.DEBUG)
    # requests_log.propagate = True

    # send to MDS
    r = requests.post(MDS_WS_ENDPOINT, params={"xml": xml_string}, headers={'Content-Type': 'application/xml; charset=UTF-8'})
    resp = xmltodict.parse(r.text)

    try:
        # this might be a KeyError or AssertionError, but either way we want to know about it and see the response
        assert resp['CUSTOrderAck']['OrderAck']['Result'] == '1'
        app.logger.info(u"Sent Order #{} to MDS".format(str(data['order_number'])))
    except:
        app.logger.exception(u"Problem sending Order #{} to MDS. Response: {}.".format(str(data['order_number']), r.text))

    # tell Shopify all is right with the world
    return "OK"


@app.route('/')
def hello_world():
    return 'Hello, world! What do you want?'


if __name__ == '__main__':
    app.run(debug=True)
