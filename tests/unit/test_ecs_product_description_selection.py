from bs4 import BeautifulSoup

from cloud_expert.ingestion.providers.aliyun.ecs.parser import parse_ecs_document as parse_aliyun
from cloud_expert.ingestion.providers.huawei_cloud.ecs.parser import (
    parse_ecs_document as parse_huawei,
)
from cloud_expert.parsing.html_adapter import HtmlDocument


def _document(html: str) -> HtmlDocument:
    soup = BeautifulSoup(html, "html.parser")
    return HtmlDocument(
        title="Synthetic ECS page",
        text=" ".join(soup.get_text(" ", strip=True).split()),
        soup=soup,
    )


def _description(records):
    product = next(record for record in records if record.record_type == "product")
    return next(field for field in product.fields if field.field_code == "product.description")


def test_huawei_description_prefers_official_body_over_navigation() -> None:
    document = _document(
        "<html><body><div>文档首页 / 弹性云服务器 ECS / 产品介绍</div>"
        "<p>弹性云服务器 ECS 是由 CPU、内存、操作系统和云硬盘组成的基础计算组件，"
        "提供按需使用的计算服务，可依据业务需要调整规格并运行应用程序。</p></body></html>"
    )
    field = _description(parse_huawei(document, source_id="synthetic", snapshot_id="synthetic"))
    assert field.locator == "html:text[1]"
    assert "基础计算组件" in field.excerpt
    assert "文档首页" not in field.excerpt


def test_aliyun_description_prefers_official_body_over_navigation() -> None:
    document = _document(
        "<html><body><div>云服务器 ECS 产品概述 产品功能 选型与定价</div>"
        "<p>云服务器 ECS 是阿里云提供的弹性扩展的云计算服务，"
        "用户可按需取得计算资源并部署应用，不必预先采购服务器硬件。</p></body></html>"
    )
    field = _description(parse_aliyun(document, source_id="synthetic", snapshot_id="synthetic"))
    assert field.locator == "html:text[1]"
    assert "云计算服务" in field.excerpt
    assert "产品概述" not in field.excerpt
