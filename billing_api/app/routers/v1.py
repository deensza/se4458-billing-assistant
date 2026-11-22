"""Version 1 of the Billing API. All routes are served under /api/v1.

A future breaking change would be added as a new router (e.g. routers/v2.py mounted at /api/v2)
while /api/v1 keeps working.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import services
from ..config import settings
from ..database import get_db
from ..errors import ApiError
from ..models import User
from ..schemas import (
    AddUsageRequest,
    AddUsageResponse,
    BillDetailedResponse,
    BillSummary,
    CalculateBillRequest,
    CalculateBillResponse,
    ErrorResponse,
    Month,
    PayBillRequest,
    PayBillResponse,
    SubscriberNo,
    TokenRequest,
    TokenResponse,
    Year,
)
from ..security import CurrentUser, create_access_token, ensure_account_access, get_current_user, verify_password

router = APIRouter(prefix="/api/v1")

DbSession = Annotated[Session, Depends(get_db)]


def _errors(*codes: int) -> dict:
    return {code: {"model": ErrorResponse} for code in codes}


# ---------------------------------------------------------------- Auth
@router.post(
    "/auth/token",
    response_model=TokenResponse,
    tags=["Authentication"],
    summary="Log in and obtain a JWT access token",
    responses=_errors(401, 422),
)
def login(body: TokenRequest, db: DbSession):
    user = db.scalars(select(User).where(User.username == body.username)).first()
    if user is None or not verify_password(body.password, user.password_hash):
        raise ApiError(401, "INVALID_CREDENTIALS", "Username or password is incorrect.")
    return TokenResponse(
        access_token=create_access_token(user.username, user.role, user.subscriber_no),
        expires_in=settings.jwt_expire_minutes * 60,
        role=user.role,
        subscriber_no=user.subscriber_no,
    )


# ---------------------------------------------------------------- Add Usage
@router.post(
    "/usage",
    status_code=201,
    response_model=AddUsageResponse,
    tags=["Usage"],
    summary="Add Usage (Phone = +10 minutes, Internet = +1 MB)",
    description=(
        "Records one usage event for the subscriber and billing month. "
        "**Auth: required** (the subscriber for their own account, or ADMIN for any account)."
    ),
    responses=_errors(401, 403, 404, 422),
)
def add_usage(body: AddUsageRequest, db: DbSession, user: CurrentUser = Depends(get_current_user)):
    ensure_account_access(user, body.subscriber_no)
    return services.add_usage(db, body.subscriber_no, body.year, body.month, body.usage_type)


# ---------------------------------------------------------------- Calculate Bill
@router.post(
    "/bills/calculate",
    response_model=CalculateBillResponse,
    tags=["Bills"],
    summary="Calculate Bill",
    description=(
        "Calculates and stores the bill for the subscriber and month from the recorded usage. "
        "Re-running it recalculates the bill and keeps payments already made. "
        "**Auth: required** (the subscriber for their own account, or ADMIN for any account)."
    ),
    responses=_errors(401, 403, 404, 422),
)
def calculate_bill(body: CalculateBillRequest, db: DbSession, user: CurrentUser = Depends(get_current_user)):
    ensure_account_access(user, body.subscriber_no)
    return services.calculate_bill(db, body.subscriber_no, body.year, body.month)


# ---------------------------------------------------------------- Query Bill
@router.get(
    "/bills",
    response_model=BillSummary,
    tags=["Bills"],
    summary="Query Bill",
    description="Returns bill total, paid amount, remaining balance and status. **Auth: none (public).**",
    responses=_errors(404, 422),
)
def query_bill(
    db: DbSession,
    subscriber_no: Annotated[SubscriberNo, Query(alias="subscriberNo")],
    month: Annotated[Month, Query()],
    year: Annotated[Year, Query()],
):
    return services.query_bill(db, subscriber_no, year, month)


# ---------------------------------------------------------------- Query Bill Detailed
@router.get(
    "/bills/detailed",
    response_model=BillDetailedResponse,
    tags=["Bills"],
    summary="Query Bill Detailed (paged usage records)",
    description=(
        "Returns the bill summary, the phone/internet charge breakdown and a page of the usage records "
        "of the month. **Auth: the subscriber (own account) or ADMIN. Paging: page, pageSize.**"
    ),
    responses=_errors(401, 403, 404, 422),
)
def query_bill_detailed(
    db: DbSession,
    subscriber_no: Annotated[SubscriberNo, Query(alias="subscriberNo")],
    month: Annotated[Month, Query()],
    year: Annotated[Year, Query()],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(alias="pageSize", ge=1, le=100)] = 20,
    user: CurrentUser = Depends(get_current_user),
):
    return services.query_bill_detailed(db, user, subscriber_no, year, month, page, page_size)


# ---------------------------------------------------------------- Pay Bill
@router.post(
    "/payments",
    status_code=201,
    response_model=PayBillResponse,
    tags=["Payments"],
    summary="Pay Bill (simulated full or partial payment)",
    description=(
        "Records a simulated payment. Rejects duplicate transaction IDs (409) and amounts larger than the "
        "remaining balance (422). No real card processing. **Auth: the subscriber (own account) or ADMIN.**"
    ),
    responses=_errors(401, 403, 404, 409, 422),
)
def pay_bill(body: PayBillRequest, db: DbSession, user: CurrentUser = Depends(get_current_user)):
    return services.pay_bill(
        db, user, body.subscriber_no, body.year, body.month, body.amount, body.transaction_id
    )
