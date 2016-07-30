# -*- coding: utf-8 -*-
from __future__ import absolute_import
from __future__ import unicode_literals

import copy
import datetime

import mock
import pytest
from sqlalchemy.orm import exc as orm_exc


from schematizer.models import AvroSchemaElement
from schematizer.models import EntityType
from schematizer.models import MetaAttributeMappingStore
from schematizer.models import Namespace
from schematizer.models import SchemaMetaAttributeMapping
from schematizer.models import Source
from schematizer.components import converters
from schematizer.models.database import session
from schematizer.logic import exceptions as sch_exc
from schematizer.logic import meta_attribute_mappers as meta_attr_logic
from testing import factories
from tests.models.testing_db import DBTestCase


class RegisterMetaAttributeBase(DBTestCase):

    def assert_equal_meta_attr_partial(self, expected, actual):
        assert expected.entity_type == actual.entity_type
        assert expected.entity_id == actual.entity_id
        assert expected.meta_attr_schema_id == actual.meta_attr_schema_id

    def assert_equal_meta_attr(self, expected, actual):
        assert expected.id == actual.id
        assert expected.created_at == actual.created_at
        assert expected.updated_at == actual.updated_at
        self.assert_equal_meta_attr_partial(expected, actual)

    def _setup_meta_attribute_mapping(self, meta_attr_schema, entity_id):
        factories.create_meta_attribute_mapping(
            meta_attr_schema.id,
            self.entity_type,
            entity_id
        )

    def test_register_non_existing_entity(self, setup_test, meta_attr_schema):
        with pytest.raises(orm_exc.NoResultFound):
            self.register_logic_method(
                meta_attr_schema.id,
                1234
            )

    def test_register_non_existing_meta_attr(self, setup_test):
        with pytest.raises(orm_exc.NoResultFound):
            self.register_logic_method(
                1234,
                self.entity.id
            )

    def test_register_first_time(self, setup_test, meta_attr_schema):
        actual = self.register_logic_method(
            meta_attr_schema.id,
            self.entity.id
        )
        expected = MetaAttributeMappingStore(
            entity_type=self.entity_type,
            entity_id=self.entity.id,
            meta_attr_schema_id=meta_attr_schema.id
        )
        self.assert_equal_meta_attr_partial(expected, actual)

    def test_idempotent_registration(self, setup_test, meta_attr_schema):
        self._setup_meta_attribute_mapping(meta_attr_schema, self.entity.id)
        first_result = self.register_logic_method(
            meta_attr_schema.id,
            self.entity.id
        )
        second_result = self.register_logic_method(
            meta_attr_schema.id,
            self.entity.id
        )
        expected = MetaAttributeMappingStore(
            entity_type=self.entity_type,
            entity_id=self.entity.id,
            meta_attr_schema_id=meta_attr_schema.id
        )
        self.assert_equal_meta_attr_partial(expected, first_result)
        self.assert_equal_meta_attr(first_result, second_result)

    def test_delete_mapping(self, setup_test, meta_attr_schema):
        self._setup_meta_attribute_mapping(meta_attr_schema, self.entity.id)
        actual = self.delete_logic_method(
            meta_attr_schema.id,
            self.entity.id
        )
        assert actual
        with pytest.raises(orm_exc.NoResultFound):
            session.query(
                MetaAttributeMappingStore
            ).filter(
                MetaAttributeMappingStore.entity_type == self.entity_type,
                MetaAttributeMappingStore.entity_id == self.entity.id,
                MetaAttributeMappingStore.meta_attr_schema_id == meta_attr_schema.id
            ).one()


class TestRegisterMetaAttributeForNamespace(RegisterMetaAttributeBase):

    @pytest.fixture
    def setup_test(self, yelp_namespace):
        self.entity_type = EntityType.NAMESPACE
        self.register_logic_method = meta_attr_logic.register_meta_attribute_mapping_for_namespace
        self.delete_logic_method = meta_attr_logic.delete_meta_attribute_mapping_for_namespace
        self.entity = yelp_namespace


class TestRegisterMetaAttributeForSource(RegisterMetaAttributeBase):

    @pytest.fixture
    def setup_test(self, biz_source):
        self.entity_type = EntityType.SOURCE
        self.register_logic_method = meta_attr_logic.register_meta_attribute_mapping_for_source
        self.delete_logic_method = meta_attr_logic.delete_meta_attribute_mapping_for_source
        self.entity = biz_source


class TestRegisterMetaAttributeForSchema(RegisterMetaAttributeBase):

    @pytest.fixture
    def setup_test(self, biz_schema):
        self.entity_type = EntityType.SCHEMA
        self.register_logic_method = meta_attr_logic.register_meta_attribute_mapping_for_schema
        self.delete_logic_method = meta_attr_logic.delete_meta_attribute_mapping_for_schema
        self.entity = biz_schema


class GetMetaAttributeBaseTest(DBTestCase):
    """MetaAttribute Mappings are supposed to be additive. In other words, a
    Source should have all the meta attributes for itself and the namespace it
    belongs to. Similarly an AvroSchema should have all the meta attributes for
    itself and the source and namespace it belongs to.

    Below are the entity structures and the meta attribute mappings I will be
    testing with:
        NamespaceA:
          - SourceA1
            - SchemaA1X
        NamespaceB

    +----+-------------+-----------+------------------+
    | id | entity_type | entity_id | meta_attr_schema |
    +----+-------------+-----------+------------------+
    |  1 |   namespace |         A |      meta_attr_1 |
    |  2 |      source |        A1 |      meta_attr_2 |
    |  3 |      schema |       A1X |      meta_attr_3 |
    |  4 |   namespace |         B |      meta_attr_4 |
    +----+-------------+-----------+------------------+
    """

    @pytest.fixture
    def namespace_A(self):
        return factories.create_namespace('yelp_meta_A')

    @pytest.fixture
    def namespace_B(self):
        return factories.create_namespace('yelp_meta_B')

    @pytest.fixture
    def source_A_1(self, namespace_A):
        return factories.create_source(
            namespace_name=namespace_A.name,
            source_name='meta_source_A_1',
            owner_email='test-meta-src@yelp.com'
        )

    @pytest.fixture
    def avro_schema_A_1_X(
        self,
        namespace_A,
        source_A_1,
        meta_attr_schema_json,
        meta_attr_schema_elements
    ):
        return factories.create_avro_schema(
            meta_attr_schema_json,
            meta_attr_schema_elements,
            topic_name='.'.join([namespace_A.name, source_A_1.name, '1']),
            namespace=namespace_A.name,
            source=source_A_1.name
        )

    def _create_meta_attribute_schema(
        self,
        source_name,
        meta_attr_schema_json,
        meta_attr_schema_elements
    ):
        return factories.create_avro_schema(
            meta_attr_schema_json,
            meta_attr_schema_elements,
            topic_name='.'.join(['yelp_meta', source_name, '1']),
            namespace='yelp_meta',
            source=source_name
        )

    @pytest.fixture
    def meta_attr_1(self, meta_attr_schema_json, meta_attr_schema_elements):
        return self._create_meta_attribute_schema(
            'meta_atr_1', meta_attr_schema_json, meta_attr_schema_elements
        )

    @pytest.fixture
    def meta_attr_2(self, meta_attr_schema_json, meta_attr_schema_elements):
        return self._create_meta_attribute_schema(
            'meta_atr_2', meta_attr_schema_json, meta_attr_schema_elements
        )

    @pytest.fixture
    def meta_attr_3(self, meta_attr_schema_json, meta_attr_schema_elements):
        return self._create_meta_attribute_schema(
            'meta_atr_3', meta_attr_schema_json, meta_attr_schema_elements
        )

    @pytest.fixture
    def meta_attr_4(self, meta_attr_schema_json, meta_attr_schema_elements):
        return self._create_meta_attribute_schema(
            'meta_atr_4', meta_attr_schema_json, meta_attr_schema_elements
        )

    @pytest.fixture
    def setup_meta_attr_mappings(
        self, meta_attr_1, meta_attr_2, meta_attr_3, meta_attr_4, namespace_A,
        source_A_1, avro_schema_A_1_X, namespace_B
    ):
        factories.create_meta_attribute_mapping(
            meta_attr_1.id,
            EntityType.NAMESPACE,
            namespace_A.id
        )
        factories.create_meta_attribute_mapping(
            meta_attr_2.id,
            EntityType.SOURCE,
            source_A_1.id
        )
        factories.create_meta_attribute_mapping(
            meta_attr_3.id,
            EntityType.SCHEMA,
            avro_schema_A_1_X.id
        )
        factories.create_meta_attribute_mapping(
            meta_attr_4.id,
            EntityType.NAMESPACE,
            namespace_B.id
        )


class TestGetMetaAttributeMappings(GetMetaAttributeBaseTest):

    def test_get_mapping_by_namespace(
        self,
        namespace_A,
        meta_attr_1,
        setup_meta_attr_mappings
    ):
        actual = meta_attr_logic.get_meta_attributes_by_namespace(namespace_A)
        expected = [meta_attr_1.id]
        assert actual == expected

    def test_get_mapping_by_source(
        self,
        source_A_1,
        meta_attr_1,
        meta_attr_2,
        setup_meta_attr_mappings
    ):
        actual = meta_attr_logic.get_meta_attributes_by_source(source_A_1)
        expected = [meta_attr_1.id, meta_attr_2.id]
        assert actual == expected

    def test_get_mapping_by_schema(
        self,
        avro_schema_A_1_X,
        meta_attr_1,
        meta_attr_2,
        meta_attr_3,
        setup_meta_attr_mappings
    ):
        actual = meta_attr_logic.get_meta_attributes_by_schema(avro_schema_A_1_X)
        expected = [meta_attr_1.id, meta_attr_2.id, meta_attr_3.id]
        assert actual == expected

    def test_get_non_existing_mapping(self, setup_meta_attr_mappings):
        fake_namespace = Namespace(name='fake_namespace')
        actual = meta_attr_logic.get_meta_attributes_by_namespace(fake_namespace)
        expected = []
        assert actual == expected


class TestAddToMetaAttrStore(GetMetaAttributeBaseTest):

    def _get_schema_meta_attr_mappings_as_dict(self, mappings):
        mappings_dict = {}
        for m in mappings:
            if m.schema_id in mappings_dict:
                mappings_dict.get(m.schema_id).add(m.meta_attr_schema_id)
            else:
                mappings_dict[m.schema_id] = {m.meta_attr_schema_id}
        return mappings_dict

    def test_add_unique_mappings(
        self,
        avro_schema_A_1_X,
        meta_attr_1,
        meta_attr_2,
        meta_attr_3,
        setup_meta_attr_mappings
    ):
        actual = meta_attr_logic.add_meta_attribute_mappings(avro_schema_A_1_X)
        expected = {
            avro_schema_A_1_X.id: {meta_attr_1.id, meta_attr_2.id, meta_attr_3.id}
        }
        assert self._get_schema_meta_attr_mappings_as_dict(actual) == expected
        idempotent_actual = meta_attr_logic.add_meta_attribute_mappings(avro_schema_A_1_X)
        assert self._get_schema_meta_attr_mappings_as_dict(idempotent_actual) == expected

    def test_add_duplicate_mappings(
        self,
        avro_schema_A_1_X,
        meta_attr_1,
        meta_attr_2,
        meta_attr_3,
        setup_meta_attr_mappings
    ):
        factories.create_meta_attribute_mapping(
            meta_attr_2.id,
            EntityType.SOURCE,
            avro_schema_A_1_X.id
        )
        actual = meta_attr_logic.add_meta_attribute_mappings(avro_schema_A_1_X)
        expected = {
            avro_schema_A_1_X.id: {meta_attr_1.id, meta_attr_2.id, meta_attr_3.id}
        }
        assert self._get_schema_meta_attr_mappings_as_dict(actual) == expected

    def test_handle_non_existing_mappings(self, biz_schema, setup_meta_attr_mappings):
        actual = meta_attr_logic.add_meta_attribute_mappings(biz_schema)
        expected = []
        assert actual == expected
